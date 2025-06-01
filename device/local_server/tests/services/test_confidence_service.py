import pytest
import os
import json
from unittest.mock import patch, AsyncMock, mock_open

from local_server.core.config import AppSettings, ConfidenceSettings, PROJECT_ROOT_DIR
from local_server.services.confidence_service import ConfidenceService, ConfidenceResult, ensure_nltk_punkt

# Ensure NLTK punkt is available for tests. 
# This might be better in a conftest.py or a session-scoped fixture if it takes time.
@pytest.fixture(scope="session", autouse=True)
def download_nltk_punkt_for_tests():
    ensure_nltk_punkt() # Call the service's own utility

DEFAULT_CONFIDENCE_SETTINGS = ConfidenceSettings(
    rouge_l_threshold=0.3,
    keyword_triggers_file="test_keywords.json" # Use a test-specific file name
)

@pytest.fixture
def mock_app_settings():
    # Returns a fresh AppSettings instance with our test confidence settings
    return AppSettings(confidence=DEFAULT_CONFIDENCE_SETTINGS)

@pytest.fixture
def confidence_service(mock_app_settings):
    # Patch the global settings object used by ConfidenceService during its instantiation
    with patch("local_server.services.confidence_service.settings", mock_app_settings):
        service = ConfidenceService()
        # The keyword_triggers_file_path will be based on PROJECT_ROOT_DIR and the test_keywords.json
        # For tests, we will often mock the file operations for load_keywords directly.
        return service

@pytest.fixture
def mock_project_root(tmp_path):
    # Creates a temporary directory to act as the project root for keyword file loading
    with patch("local_server.services.confidence_service.PROJECT_ROOT_DIR", str(tmp_path)):
        # Also need to patch it for the config module if settings are re-read or keyword_triggers_file_path is re-evaluated
        with patch("local_server.core.config.PROJECT_ROOT_DIR", str(tmp_path)):
            yield tmp_path

@pytest.mark.asyncio
async def test_confidence_service_initialization(confidence_service, mock_app_settings, mock_project_root):
    assert confidence_service.rouge_threshold == DEFAULT_CONFIDENCE_SETTINGS.rouge_l_threshold
    expected_path = os.path.join(str(mock_project_root), "config", DEFAULT_CONFIDENCE_SETTINGS.keyword_triggers_file)
    assert confidence_service.keyword_triggers_file_path == expected_path
    assert confidence_service.keyword_triggers == [] # Not loaded yet

@pytest.mark.asyncio
async def test_load_keywords_success(confidence_service, mock_project_root):
    config_dir = mock_project_root / "config"
    config_dir.mkdir()
    keywords_file = config_dir / DEFAULT_CONFIDENCE_SETTINGS.keyword_triggers_file
    test_data = ["Test Keyword", "trigger happy", "  LoWeRCaSe  "]
    expected_keywords = ["test keyword", "trigger happy", "lowercase"]
    with open(keywords_file, "w") as f:
        json.dump(test_data, f)

    await confidence_service.load_keywords()
    assert sorted(confidence_service.keyword_triggers) == sorted(expected_keywords)

@pytest.mark.asyncio
async def test_load_keywords_file_not_found(confidence_service, mock_project_root, caplog):
    # Ensure config dir exists but file does not
    config_dir = mock_project_root / "config"
    config_dir.mkdir()
    
    await confidence_service.load_keywords()
    assert confidence_service.keyword_triggers == []
    expected_path = os.path.join(str(mock_project_root), "config", DEFAULT_CONFIDENCE_SETTINGS.keyword_triggers_file)
    assert f"Keyword triggers file not found at {expected_path}. Creating an empty one." in caplog.text
    assert os.path.exists(expected_path) # Check if empty file was created
    with open(expected_path, "r") as f:
        assert json.load(f) == []

@pytest.mark.asyncio
async def test_load_keywords_invalid_json(confidence_service, mock_project_root, caplog):
    config_dir = mock_project_root / "config"
    config_dir.mkdir()
    keywords_file = config_dir / DEFAULT_CONFIDENCE_SETTINGS.keyword_triggers_file
    with open(keywords_file, "w") as f:
        f.write("not a valid json{")

    await confidence_service.load_keywords()
    assert confidence_service.keyword_triggers == []
    assert "Error decoding JSON" in caplog.text

@pytest.mark.asyncio
async def test_load_keywords_not_a_list(confidence_service, mock_project_root, caplog):
    config_dir = mock_project_root / "config"
    config_dir.mkdir()
    keywords_file = config_dir / DEFAULT_CONFIDENCE_SETTINGS.keyword_triggers_file
    with open(keywords_file, "w") as f:
        json.dump({"oops": "not a list"}, f)

    await confidence_service.load_keywords()
    assert confidence_service.keyword_triggers == []
    assert "does not contain a list of strings" in caplog.text


# Test _calculate_rouge_l
# Note: rouge_score library itself should be trusted. We test our usage.
def test_calculate_rouge_l_basic(confidence_service):
    # These scores are illustrative and depend on the exact tokenizer and stemming.
    # It is better to test for behavior (e.g. perfect match = 1.0) than exact scores for arbitrary strings.
    gen = "The quick brown fox jumps over the lazy dog."
    ref = "The quick brown fox jumps over the lazy dog."
    f1, _ = confidence_service._calculate_rouge_l(gen, ref)
    assert f1 == pytest.approx(1.0)

    gen = "This is a test sentence."
    ref = "A completely different sentence for testing."
    f1, _ = confidence_service._calculate_rouge_l(gen, ref)
    assert 0.0 <= f1 < 1.0 

    gen = "partial match here"
    ref = "complete partial match here please"
    f1, _ = confidence_service._calculate_rouge_l(gen, ref)
    assert f1 > 0.0 and f1 < 1.0

def test_calculate_rouge_l_empty_strings(confidence_service):
    f1, _ = confidence_service._calculate_rouge_l("", "reference")
    assert f1 == 0.0
    f1, _ = confidence_service._calculate_rouge_l("generated", "")
    assert f1 == 0.0
    f1, _ = confidence_service._calculate_rouge_l("", "")
    assert f1 == 0.0

# Test _check_keywords
@pytest.mark.asyncio
async def test_check_keywords(confidence_service, mock_project_root):
    # Load some keywords first
    config_dir = mock_project_root / "config"
    config_dir.mkdir()
    keywords_file = config_dir / DEFAULT_CONFIDENCE_SETTINGS.keyword_triggers_file
    test_data = ["urgent", "help needed", "critical error"]
    with open(keywords_file, "w") as f:
        json.dump(test_data, f)
    await confidence_service.load_keywords()

    assert confidence_service._check_keywords("This is an URGENT request.") == ["urgent"]
    assert confidence_service._check_keywords("I need some HELP NEEDED with this.") == ["help needed"]
    assert sorted(confidence_service._check_keywords("Urgent: critical error found!")) == sorted(["urgent", "critical error"])
    assert confidence_service._check_keywords("Everything is fine.") == []
    assert confidence_service._check_keywords("") == []

@pytest.mark.asyncio
async def test_check_keywords_no_keywords_loaded(confidence_service):
    confidence_service.keyword_triggers = [] # Ensure no keywords are loaded
    assert confidence_service._check_keywords("This is an URGENT request.") == []

# Test assess method
@pytest.mark.asyncio
async def test_assess_high_confidence(confidence_service, mock_project_root):
    # Mock _calculate_rouge_l to return a high score
    with patch.object(confidence_service, "_calculate_rouge_l", return_value=(0.8, {})) as mock_rouge:
        # Ensure no keywords are loaded or they don't match
        confidence_service.keyword_triggers = []
        
        result = await confidence_service.assess("Generated good text", "Original prompt")
        
        assert result.needs_refinement is False
        assert result.score == 0.8
        assert result.keywords_found == []
        assert "High confidence" in result.details["reason_for_refinement"]
        mock_rouge.assert_called_once_with(generated_text="Generated good text", reference_text="Original prompt")

@pytest.mark.asyncio
async def test_assess_low_rouge_score(confidence_service, mock_project_root):
    with patch.object(confidence_service, "_calculate_rouge_l", return_value=(0.1, {})) as mock_rouge:
        confidence_service.keyword_triggers = []
        
        result = await confidence_service.assess("Generated poor text", "Original prompt")
        
        assert result.needs_refinement is True
        assert result.score == 0.1
        assert result.keywords_found == []
        assert f"ROUGE-L F1 score (0.1000) below threshold ({confidence_service.rouge_threshold})" in result.details["reason_for_refinement"]

@pytest.mark.asyncio
async def test_assess_keyword_trigger(confidence_service, mock_project_root):
    # Load a keyword
    config_dir = mock_project_root / "config"
    config_dir.mkdir()
    keywords_file = config_dir / DEFAULT_CONFIDENCE_SETTINGS.keyword_triggers_file
    with open(keywords_file, "w") as f: json.dump(["emergency"], f)
    await confidence_service.load_keywords()

    with patch.object(confidence_service, "_calculate_rouge_l", return_value=(0.9, {})) as mock_rouge: # High ROUGE
        result = await confidence_service.assess("Generated text", "This is an emergency prompt")
        
        assert result.needs_refinement is True
        assert result.score == 0.9 # ROUGE score is still calculated
        assert result.keywords_found == ["emergency"]
        assert "Keyword trigger(s) in prompt: [\'emergency\']" in result.details["reason_for_refinement"]

@pytest.mark.asyncio
async def test_assess_keywords_not_loaded_attempts_load(confidence_service, mock_project_root, caplog):
    # Ensure keywords are not loaded initially
    confidence_service.keyword_triggers = []
    
    # Setup a keyword file that load_keywords (when called by assess) can find
    config_dir = mock_project_root / "config"
    config_dir.mkdir()
    keywords_file = config_dir / DEFAULT_CONFIDENCE_SETTINGS.keyword_triggers_file
    with open(keywords_file, "w") as f: json.dump(["special"], f)

    with patch.object(confidence_service, "_calculate_rouge_l", return_value=(0.9, {})):
        result = await confidence_service.assess("Some text", "This is a special prompt")
        
        assert "Keywords not loaded in ConfidenceService instance, attempting to load now." in caplog.text
        assert result.needs_refinement is True # Due to "special" keyword
        assert result.keywords_found == ["special"]
        assert len(confidence_service.keyword_triggers) > 0 # Check they were loaded

