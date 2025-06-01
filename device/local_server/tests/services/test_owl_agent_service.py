import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from local_server.core.config import AppSettings, VLLMSettings, OwlAgentSettings
from local_server.services.vllm_service import VLLMService
from local_server.services.owl_agent_service import OwlAgentService, OwlAgentServiceError

# Default settings for tests
DEFAULT_VLLM_SETTINGS = VLLMSettings(api_base_url="http://fakevllm:8000/v1", model_name_or_path="fake_model")
DEFAULT_OWL_AGENT_SETTINGS = OwlAgentSettings(use_local_vllm=True)

@pytest.fixture
def mock_app_settings():
    return AppSettings(vllm=DEFAULT_VLLM_SETTINGS, owl_agent=DEFAULT_OWL_AGENT_SETTINGS)

@pytest.fixture
def mock_vllm_service():
    # Create a mock VLLMService instance
    # We don't need a real http_client for this mock, as OwlAgentService doesn't directly use it.
    # It uses the vllm_service_instance conceptually for configuration.
    mock_service = MagicMock(spec=VLLMService)
    # If OwlAgentService._initialize_agent were to call vllm_service.check_health(), we would mock it:
    # mock_service.check_health = AsyncMock(return_value=True) 
    return mock_service

@pytest.fixture
def owl_agent_service(mock_vllm_service, mock_app_settings):
    # Patch the global settings object used by OwlAgentService during its instantiation
    with patch("local_server.services.owl_agent_service.settings", mock_app_settings):
        service = OwlAgentService(vllm_service_instance=mock_vllm_service)
        return service

# Test Initialization
def test_owl_agent_service_initialization_success(owl_agent_service, mock_vllm_service, mock_app_settings):
    assert owl_agent_service.vllm_service == mock_vllm_service
    assert owl_agent_service.is_initialized is True # Based on current simulation
    assert owl_agent_service._owl_agent_instance == "SimulatedOwlAgentInstance"
    expected_llm_config = {
        "model_type": "openai",
        "model_config_dict": {
            "model": mock_app_settings.vllm.model_name_or_path,
            "api_base": mock_app_settings.vllm.api_base_url,
            "api_key": "DUMMY_KEY_FOR_LOCAL_VLLM",
            "api_type": "openai",
        }
    }
    assert owl_agent_service.owl_llm_config == expected_llm_config

def test_owl_agent_service_initialization_use_local_vllm_false(mock_vllm_service, mock_app_settings):
    # Override use_local_vllm for this test
    custom_owl_settings = OwlAgentSettings(use_local_vllm=False)
    custom_app_settings = AppSettings(vllm=DEFAULT_VLLM_SETTINGS, owl_agent=custom_owl_settings)
    
    with patch("local_server.services.owl_agent_service.settings", custom_app_settings):
        service = OwlAgentService(vllm_service_instance=mock_vllm_service)
        assert service.is_initialized is False # As per current _initialize_agent logic
        assert service._owl_agent_instance is None

# Test execute_task
@pytest.mark.asyncio
async def test_execute_task_success(owl_agent_service, mock_app_settings):
    task_desc = "Plan a trip to Mars."
    result = await owl_agent_service.execute_task(task_desc)

    assert result["status"] == "success"
    assert "SIMULATED result from Owl Agent" in result["agent_outcome"]
    assert task_desc[:150] in result["agent_outcome"]
    assert result["execution_details"]["message"] == "Task execution was simulated successfully."
    assert result["execution_details"]["config_used"]["model_config_dict"]["api_base"] == mock_app_settings.vllm.api_base_url

@pytest.mark.asyncio
async def test_execute_task_with_override(owl_agent_service, caplog):
    task_desc = "Write a poem."
    override_config = {"style": "haiku"}
    # Current simulation doesn't use override, but we test it's logged
    await owl_agent_service.execute_task(task_desc, agent_config_override=override_config)
    assert f"Applying agent config override: {override_config}" in caplog.text

@pytest.mark.asyncio
async def test_execute_task_agent_not_initialized(mock_vllm_service, mock_app_settings):
    custom_owl_settings = OwlAgentSettings(use_local_vllm=False)
    custom_app_settings = AppSettings(vllm=DEFAULT_VLLM_SETTINGS, owl_agent=custom_owl_settings)
    
    with patch("local_server.services.owl_agent_service.settings", custom_app_settings):
        service_uninitialized = OwlAgentService(vllm_service_instance=mock_vllm_service)
    
    with pytest.raises(OwlAgentServiceError) as excinfo:
        await service_uninitialized.execute_task("This should fail.")
    assert "Owl Agent is not initialized" in str(excinfo.value)

@pytest.mark.asyncio
async def test_execute_task_simulated_internal_error(owl_agent_service):
    # To test the exception handling within the (simulated) execute_task method
    # we need to make the simulated part raise an error.
    # Since the simulation is simple, we patch `asyncio.sleep` to raise an error.
    with patch("asyncio.sleep", AsyncMock(side_effect=RuntimeError("Simulated agent crash"))):
        with pytest.raises(OwlAgentServiceError) as excinfo:
            await owl_agent_service.execute_task("Task that will crash agent")
        assert "Error during Owl Agent task execution: Simulated agent crash" in str(excinfo.value)
        assert isinstance(excinfo.value.underlying_exception, RuntimeError)

# Test check_agent_health
@pytest.mark.asyncio
async def test_check_agent_health_initialized(owl_agent_service, mock_app_settings):
    health = await owl_agent_service.check_agent_health()
    assert health["status"] == "healthy"
    assert "Owl Agent is initialized (simulated)" in health["message"]
    assert health["details"]["configured_llm_base"] == mock_app_settings.vllm.api_base_url

@pytest.mark.asyncio
async def test_check_agent_health_uninitialized(mock_vllm_service, mock_app_settings):
    custom_owl_settings = OwlAgentSettings(use_local_vllm=False)
    custom_app_settings = AppSettings(vllm=DEFAULT_VLLM_SETTINGS, owl_agent=custom_owl_settings)
    with patch("local_server.services.owl_agent_service.settings", custom_app_settings):
        service_uninitialized = OwlAgentService(vllm_service_instance=mock_vllm_service)
    
    health = await service_uninitialized.check_agent_health()
    assert health["status"] == "uninitialized"
    assert "Owl Agent is not initialized" in health["message"]

