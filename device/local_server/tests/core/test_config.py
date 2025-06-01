import pytest
import os
import json
from unittest.mock import patch, mock_open

from local_server.core.config import AppSettings, VLLMSettings, ConfidenceSettings, RemoteServerSettings, OwlAgentSettings, load_keyword_triggers, PROJECT_ROOT_DIR

# Ensure this test module can find the local_server package
# This might require setting PYTHONPATH or specific pytest configurations if tests are run from a different root.

@pytest.fixture(scope="function", autouse=True)
def reset_env_and_globals():
    """Resets environment variables and global keyword cache before/after each test."""
    original_env = os.environ.copy()
    # Clear any potentially conflicting env vars used by AppSettings
    for key in list(os.environ.keys()):
        if key.startswith("LOCAL_SERVER_"):
            del os.environ[key]
    
    # Reset the global keyword trigger cache in config.py
    # Accessing it directly like this is a bit of a hack for testing, 
    # ideally, the config module would provide a reset function.
    import local_server.core.config
    local_server.core.config._loaded_keyword_triggers = None
    
    yield
    
    os.environ.clear()
    os.environ.update(original_env)
    local_server.core.config._loaded_keyword_triggers = None


class TestAppSettings:
    def test_default_settings_load(self):
        settings = AppSettings()
        assert settings.local_server_id == "local_server_dev_01"
        assert settings.log_level == "INFO"
        assert isinstance(settings.vllm, VLLMSettings)
        assert settings.vllm.api_base_url == "http://localhost:8000/v1"
        assert settings.vllm.model_name_or_path == "Qwen/Qwen1.5-14B-Chat-AWQ"
        assert isinstance(settings.confidence, ConfidenceSettings)
        assert settings.confidence.rouge_l_threshold == 0.3
        assert settings.confidence.keyword_triggers_file == "keyword_triggers.json"
        assert isinstance(settings.remote_server, RemoteServerSettings)
        assert settings.remote_server.host == "127.0.0.1"
        assert isinstance(settings.owl_agent, OwlAgentSettings)
        assert settings.owl_agent.use_local_vllm is True

    def test_env_variable_override(self):
        os.environ["LOCAL_SERVER_LOG_LEVEL"] = "DEBUG"
        os.environ["LOCAL_SERVER_VLLM__API_BASE_URL"] = "http://testhost:1234/v1_test"
        os.environ["LOCAL_SERVER_CONFIDENCE__ROUGE_L_THRESHOLD"] = "0.5"
        os.environ["LOCAL_SERVER_REMOTE_SERVER__HOST"] = "remote.example.com"
        os.environ["LOCAL_SERVER_OWL_AGENT__USE_LOCAL_VLLM"] = "false"
        os.environ["LOCAL_SERVER_LOCAL_SERVER_ID"] = "test_server_007"

        settings = AppSettings() # Reloads settings with env vars

        assert settings.log_level == "DEBUG"
        assert settings.vllm.api_base_url == "http://testhost:1234/v1_test"
        assert settings.confidence.rouge_l_threshold == 0.5
        assert settings.remote_server.host == "remote.example.com"
        assert settings.owl_agent.use_local_vllm is False
        assert settings.local_server_id == "test_server_007"

    def test_env_file_loading(self, tmp_path):
        # Create a temporary .env file in a temporary project root
        temp_project_root = tmp_path
        temp_env_file = temp_project_root / ".env"
        with open(temp_env_file, "w") as f:
            f.write("LOCAL_SERVER_LOG_LEVEL=WARNING\n")
            f.write("LOCAL_SERVER_VLLM__DEFAULT_MAX_TOKENS=512\n")

        # Patch PROJECT_ROOT_DIR to point to our temporary project root
        with patch("local_server.core.config.PROJECT_ROOT_DIR", str(temp_project_root)):
            settings = AppSettings() # This should load the .env file

            assert settings.log_level == "WARNING"
            assert settings.vllm.default_max_tokens == 512
            # Ensure other defaults are still there
            assert settings.vllm.api_base_url == "http://localhost:8000/v1"

@pytest.mark.asyncio
async def test_load_keyword_triggers_file_exists_valid_json(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    keywords_file = config_dir / "test_keywords.json"
    test_keywords = ["hello world", "Test Keyword", "  extra space  "]
    expected_keywords = ["hello world", "test keyword", "extra space"]
    with open(keywords_file, "w") as f:
        json.dump(test_keywords, f)

    with patch("local_server.core.config.PROJECT_ROOT_DIR", str(tmp_path)):
        with patch("local_server.core.config.settings.confidence.keyword_triggers_file", "test_keywords.json"):
            loaded_keywords = await load_keyword_triggers()
            assert sorted(loaded_keywords) == sorted(expected_keywords)
            # Test caching
            loaded_keywords_cached = await load_keyword_triggers()
            assert sorted(loaded_keywords_cached) == sorted(expected_keywords)

@pytest.mark.asyncio
async def test_load_keyword_triggers_file_not_exists(tmp_path, caplog):
    # Ensure the config directory exists, but the file does not
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    
    with patch("local_server.core.config.PROJECT_ROOT_DIR", str(tmp_path)):
        with patch("local_server.core.config.settings.confidence.keyword_triggers_file", "non_existent_keywords.json"):
            loaded_keywords = await load_keyword_triggers()
            assert loaded_keywords == []
            assert f"Keyword triggers file not found at {config_dir / 'non_existent_keywords.json'}. Creating an empty one." in caplog.text
            # Check if the empty file was created
            assert os.path.exists(config_dir / "non_existent_keywords.json")
            with open(config_dir / "non_existent_keywords.json", "r") as f:
                assert json.load(f) == []

@pytest.mark.asyncio
async def test_load_keyword_triggers_invalid_json(tmp_path, caplog):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    keywords_file = config_dir / "invalid_keywords.json"
    with open(keywords_file, "w") as f:
        f.write("this is not json")

    with patch("local_server.core.config.PROJECT_ROOT_DIR", str(tmp_path)):
        with patch("local_server.core.config.settings.confidence.keyword_triggers_file", "invalid_keywords.json"):
            loaded_keywords = await load_keyword_triggers()
            assert loaded_keywords == []
            assert f"Error decoding JSON from keyword triggers file {keywords_file}" in caplog.text

@pytest.mark.asyncio
async def test_load_keyword_triggers_not_a_list(tmp_path, caplog):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    keywords_file = config_dir / "not_list_keywords.json"
    with open(keywords_file, "w") as f:
        json.dump({"key": "value"}, f) # Not a list

    with patch("local_server.core.config.PROJECT_ROOT_DIR", str(tmp_path)):
        with patch("local_server.core.config.settings.confidence.keyword_triggers_file", "not_list_keywords.json"):
            loaded_keywords = await load_keyword_triggers()
            assert loaded_keywords == []
            assert f"Keyword triggers file {keywords_file} does not contain a list of strings" in caplog.text

@pytest.mark.asyncio
async def test_load_keyword_triggers_empty_list(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    keywords_file = config_dir / "empty_keywords.json"
    with open(keywords_file, "w") as f:
        json.dump([], f)

    with patch("local_server.core.config.PROJECT_ROOT_DIR", str(tmp_path)):
        with patch("local_server.core.config.settings.confidence.keyword_triggers_file", "empty_keywords.json"):
            loaded_keywords = await load_keyword_triggers()
            assert loaded_keywords == []

