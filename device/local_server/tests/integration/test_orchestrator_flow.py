import pytest
import asyncio
import json
import httpx
from unittest.mock import patch, AsyncMock, MagicMock

from local_server.core.config import AppSettings, VLLMSettings, ConfidenceSettings, RemoteServerSettings, OwlAgentSettings, PROJECT_ROOT_DIR
from local_server.services.vllm_service import VLLMService
from local_server.services.confidence_service import ConfidenceService, ConfidenceResult, ensure_nltk_punkt
from local_server.services.owl_agent_service import OwlAgentService # Will be mocked for this specific test
from local_server.communication.tcp_client import TCPRemoteClient
from local_server.services.task_orchestrator import TaskOrchestrator
from local_server.communication.protocol_models import LocalConfidentResultNotificationPayload, CloudRefinementResponseToLocalPayload, LocalRequestCloudRefinementPayload

# Ensure NLTK punkt is available for tests.
@pytest.fixture(scope="session", autouse=True)
def download_nltk_punkt_for_integration_tests():
    ensure_nltk_punkt()

@pytest.fixture
def temp_keyword_file(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    keyword_file = config_dir / "integration_keywords.json"
    with open(keyword_file, "w") as f:
        json.dump(["critical error", "urgent help"], f)
    return keyword_file.name # Return just the filename

@pytest.fixture
def integration_settings(temp_keyword_file, tmp_path):
    # Patch PROJECT_ROOT_DIR to use tmp_path for keyword file loading
    with patch("local_server.core.config.PROJECT_ROOT_DIR", str(tmp_path)):
        settings = AppSettings(
            local_server_id="integration_test_server",
            log_level="DEBUG", # More verbose for tests
            vllm=VLLMSettings(
                api_base_url="http://mock-vllm-api:8000/v1",
                model_name_or_path="mock_model/integration_test_model",
                request_timeout=2.0 # Short timeout
            ),
            confidence=ConfidenceSettings(
                rouge_l_threshold=0.7, # Set a threshold for testing
                keyword_triggers_file=temp_keyword_file # Use the temp file
            ),
            owl_agent=OwlAgentSettings(use_local_vllm=True),
            remote_server=RemoteServerSettings(
                host="127.0.0.1",
                command_port=9997, # Unique port for these tests
                cloud_request_timeout_seconds=1.0,
                heartbeat_interval_seconds=60, # Don't need frequent heartbeats for this test
                tcp_client_reconnect_delay_seconds=1
            )
        )
        yield settings

@pytest.fixture
async def integration_vllm_service(integration_settings):
    # For integration tests, we use a real VLLMService but mock the HTTP client it uses.
    # The httpx_mock fixture will be used in the test function itself.
    async_http_client = httpx.AsyncClient() # Real client, but requests will be mocked by httpx_mock
    with patch("local_server.services.vllm_service.settings", integration_settings):
        service = VLLMService(http_client=async_http_client)
        yield service
        await async_http_client.aclose()

@pytest.fixture
async def integration_confidence_service(integration_settings, tmp_path):
    # Patch PROJECT_ROOT_DIR for ConfidenceService as well
    with patch("local_server.services.confidence_service.PROJECT_ROOT_DIR", str(tmp_path)):
        with patch("local_server.services.confidence_service.settings", integration_settings):
            service = ConfidenceService()
            await service.load_keywords() # Load keywords from the temp file
            return service

@pytest.fixture
def mock_integration_owl_agent_service():
    # OwlAgentService is complex and might have its own external dependencies (actual Owl lib).
    # For an orchestrator integration test, mocking it is often sufficient.
    service = MagicMock(spec=OwlAgentService)
    service.execute_task = AsyncMock(return_value={"status": "success", "agent_outcome": "Mocked Owl Result"})
    service.check_agent_health = AsyncMock(return_value={"status": "healthy"})
    return service

@pytest.fixture
async def integration_tcp_client(integration_settings):
    # For this integration test, we will mock the actual send methods of TCPRemoteClient
    # to avoid needing a real TCP server, focusing on orchestrator logic.
    # A more in-depth TCP integration test would use a mock server (like in test_tcp_client.py).
    with patch("local_server.communication.tcp_client.settings", integration_settings):
        client = TCPRemoteClient(
            host=integration_settings.remote_server.host,
            port=integration_settings.remote_server.command_port,
            client_id=integration_settings.local_server_id
        )
        # Mock the low-level send and request methods
        client.connect = AsyncMock(return_value=True) # Assume connection is fine
        client.is_connected = True
        client.send_message = AsyncMock(return_value=True) # Generic send
        client.send_heartbeat = AsyncMock(return_value=True)
        client.send_confident_result_notification = AsyncMock(return_value=True)
        client.request_cloud_refinement = AsyncMock() # Will be configured per test
        client.close = AsyncMock()
        client._ensure_connected_and_ready = AsyncMock() # Bypass connection logic for sending
        client._receive_loop_task = AsyncMock() # Mock background tasks
        client._heartbeat_task = AsyncMock()
        client._maintain_connection_task = AsyncMock()
        yield client
        # No explicit close needed as methods are mocked

@pytest.fixture
def integration_task_orchestrator(integration_vllm_service, integration_confidence_service, mock_integration_owl_agent_service, integration_tcp_client, integration_settings):
    with patch("local_server.services.task_orchestrator.settings", integration_settings):
        orchestrator = TaskOrchestrator(
            vllm_service=integration_vllm_service,
            confidence_service=integration_confidence_service,
            owl_agent_service=mock_integration_owl_agent_service, # Mocked
            tcp_remote_client=integration_tcp_client # Mocked sends
        )
        return orchestrator

@pytest.mark.asyncio
async def test_orchestrator_full_flow_local_high_confidence(integration_task_orchestrator, integration_vllm_service, integration_confidence_service, integration_tcp_client, integration_settings, httpx_mock):
    user_prompt = "Write a short poem about spring."
    vllm_generated_text = "Green shoots appear, birds sing their song, spring is here, winter is gone."

    # Mock vLLM API response for the VLLMService
    httpx_mock.add_response(
        url=integration_vllm_service.chat_completions_url,
        json={"choices": [{"message": {"content": vllm_generated_text}}], "usage": {"total_tokens": 20}},
        status_code=200
    )

    # ConfidenceService will use its real logic with the loaded keywords and ROUGE threshold.
    # For this text and prompt, ROUGE should be high, and no keywords from temp_keyword_file match.
    # integration_settings.confidence.rouge_l_threshold is 0.7

    result = await integration_task_orchestrator.process_user_request_full_flow(user_prompt)

    assert result["result_text"] == vllm_generated_text
    assert result["source"] == "local_high_confidence"
    assert result["error"] is None
    
    # Check that VLLMService was called
    assert len(httpx_mock.get_requests()) == 1
    vllm_request = httpx_mock.get_requests()[0]
    assert json.loads(vllm_request.content)["messages"][0]["content"] == user_prompt

    # Check that ConfidenceService.assess was called (implicitly, by checking its effect)
    # We know it was high confidence because no cloud refinement was requested.
    # We can also check the details in the result if needed.
    assert result["details"]["stages"][1]["name"] == "confidence_assessment"
    assert result["details"]["stages"][1]["assessment"]["needs_refinement"] is False
    assert result["details"]["stages"][1]["assessment"]["score"] > integration_settings.confidence.rouge_l_threshold

    # Check that TCPClient.send_confident_result_notification was called
    integration_tcp_client.send_confident_result_notification.assert_called_once()
    notification_payload = integration_tcp_client.send_confident_result_notification.call_args[0][0]
    assert isinstance(notification_payload, LocalConfidentResultNotificationPayload)
    assert notification_payload.original_user_prompt == user_prompt
    assert notification_payload.local_model_final_result == vllm_generated_text

    # Ensure cloud refinement was not called
    integration_tcp_client.request_cloud_refinement.assert_not_called()

@pytest.mark.asyncio
async def test_orchestrator_full_flow_low_confidence_keyword_trigger_cloud_success(
    integration_task_orchestrator, integration_vllm_service, 
    integration_confidence_service, integration_tcp_client, 
    integration_settings, httpx_mock
):
    user_prompt = "I have a critical error in my system, I need urgent help!"
    vllm_generated_text = "Okay, I will try to help with the critical error."
    cloud_refined_text = "Understood. For critical errors requiring urgent help, please contact support at 123-4567."

    # Mock vLLM API response
    httpx_mock.add_response(
        url=integration_vllm_service.chat_completions_url,
        json={"choices": [{"message": {"content": vllm_generated_text}}], "usage": {"total_tokens": 15}},
        status_code=200
    )

    # ConfidenceService will find "critical error" and "urgent help" from temp_keyword_file.
    # This should trigger `needs_refinement = True` regardless of ROUGE score.

    # Mock TCPClient response for cloud refinement
    integration_tcp_client.request_cloud_refinement.return_value = CloudRefinementResponseToLocalPayload(
        status="success", refined_result=cloud_refined_text, cloud_tokens_consumed=50
    )

    result = await integration_task_orchestrator.process_user_request_full_flow(user_prompt)

    assert result["result_text"] == cloud_refined_text
    assert result["source"] == "cloud_refined_success"
    assert result["error"] is None

    # Check VLLMService call
    assert len(httpx_mock.get_requests()) == 1

    # Check ConfidenceService assessment details
    confidence_stage = result["details"]["stages"][1]["assessment"]
    assert confidence_stage["needs_refinement"] is True
    assert "critical error" in confidence_stage["keywords_found"]
    assert "urgent help" in confidence_stage["keywords_found"]

    # Check TCPClient.request_cloud_refinement was called
    integration_tcp_client.request_cloud_refinement.assert_called_once()
    request_payload = integration_tcp_client.request_cloud_refinement.call_args[0][0]
    assert isinstance(request_payload, LocalRequestCloudRefinementPayload)
    assert request_payload.original_user_prompt == user_prompt
    assert request_payload.local_model_draft_result == vllm_generated_text

    # Ensure confident notification was NOT called
    integration_tcp_client.send_confident_result_notification.assert_not_called()

