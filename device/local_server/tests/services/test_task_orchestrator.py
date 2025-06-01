import pytest
import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from local_server.core.config import AppSettings, VLLMSettings, ConfidenceSettings, OwlAgentSettings, RemoteServerSettings
from local_server.services.task_orchestrator import TaskOrchestrator, TaskOrchestratorError
from local_server.services.vllm_service import VLLMService, VLLMServiceError
from local_server.services.confidence_service import ConfidenceService, ConfidenceResult
from local_server.services.owl_agent_service import OwlAgentService, OwlAgentServiceError
from local_server.communication.tcp_client import TCPRemoteClient, TCPClientError, TCPClientTimeoutError
from local_server.communication.protocol_models import (
    BaseMessage, RemoteCommandToLocalPayload, ExecuteOwlTaskDetails, QueryLocalModelDirectDetails, GetLocalStatusDetails,
    LocalResponseToRemotePayload, LocalRequestCloudRefinementPayload, CloudRefinementResponseToLocalPayload,
    ConfidenceAssessmentData, LocalConfidentResultNotificationPayload
)

# --- Fixtures for Mocks and Settings ---
@pytest.fixture
def mock_settings():
    return AppSettings(
        local_server_id="test_orchestrator_server",
        vllm=VLLMSettings(),
        confidence=ConfidenceSettings(),
        owl_agent=OwlAgentSettings(),
        remote_server=RemoteServerSettings(cloud_request_timeout_seconds=1.0) # Short timeout for tests
    )

@pytest.fixture
def mock_vllm_service():
    service = MagicMock(spec=VLLMService)
    service.generate_response = AsyncMock()
    service.check_health = AsyncMock(return_value=True)
    return service

@pytest.fixture
def mock_confidence_service():
    service = MagicMock(spec=ConfidenceService)
    service.assess = AsyncMock()
    # Default: high confidence, no refinement needed
    service.assess.return_value = ConfidenceResult(needs_refinement=False, score=0.9, keywords_found=[], details={})
    return service

@pytest.fixture
def mock_owl_agent_service():
    service = MagicMock(spec=OwlAgentService)
    service.execute_task = AsyncMock()
    service.check_agent_health = AsyncMock(return_value={"status": "healthy"})
    return service

@pytest.fixture
def mock_tcp_client():
    client = MagicMock(spec=TCPRemoteClient)
    client.request_cloud_refinement = AsyncMock()
    client.send_confident_result_notification = AsyncMock()
    client.is_connected = True # Assume connected for most tests
    return client

@pytest.fixture
def task_orchestrator(mock_vllm_service, mock_confidence_service, mock_owl_agent_service, mock_tcp_client, mock_settings):
    # Patch the global settings object used by TaskOrchestrator if it imports it directly
    # (Currently, it receives settings through its dependencies or their configs)
    with patch("local_server.services.task_orchestrator.settings", mock_settings):
        orchestrator = TaskOrchestrator(
            vllm_service=mock_vllm_service,
            confidence_service=mock_confidence_service,
            owl_agent_service=mock_owl_agent_service,
            tcp_remote_client=mock_tcp_client
        )
        return orchestrator

# --- Tests for process_user_request_full_flow ---
@pytest.mark.asyncio
async def test_process_user_request_high_confidence(task_orchestrator, mock_vllm_service, mock_confidence_service, mock_tcp_client):
    user_prompt = "Tell me a joke."
    local_llm_output = "Why did the chicken cross the road?"
    mock_vllm_service.generate_response.return_value = {"choices": [{"message": {"content": local_llm_output}}]}
    # Confidence service already mocked to return high confidence by default

    result = await task_orchestrator.process_user_request_full_flow(user_prompt)

    assert result["result_text"] == local_llm_output
    assert result["source"] == "local_high_confidence"
    assert result["error"] is None
    mock_vllm_service.generate_response.assert_called_once_with(prompt=user_prompt)
    mock_confidence_service.assess.assert_called_once_with(generated_text=local_llm_output, original_prompt=user_prompt)
    mock_tcp_client.request_cloud_refinement.assert_not_called()
    mock_tcp_client.send_confident_result_notification.assert_called_once()
    notification_payload = mock_tcp_client.send_confident_result_notification.call_args[0][0]
    assert isinstance(notification_payload, LocalConfidentResultNotificationPayload)
    assert notification_payload.local_model_final_result == local_llm_output

@pytest.mark.asyncio
async def test_process_user_request_low_confidence_cloud_success(task_orchestrator, mock_vllm_service, mock_confidence_service, mock_tcp_client):
    user_prompt = "Explain quantum physics."
    local_llm_output = "It's complicated."
    cloud_refined_output = "Quantum physics is the study of matter and energy at the most fundamental level."
    
    mock_vllm_service.generate_response.return_value = {"choices": [{"message": {"content": local_llm_output}}]}
    mock_confidence_service.assess.return_value = ConfidenceResult(needs_refinement=True, score=0.2, keywords_found=[], details={})
    mock_tcp_client.request_cloud_refinement.return_value = CloudRefinementResponseToLocalPayload(
        status="success", refined_result=cloud_refined_output, cloud_tokens_consumed=100
    )

    result = await task_orchestrator.process_user_request_full_flow(user_prompt)

    assert result["result_text"] == cloud_refined_output
    assert result["source"] == "cloud_refined_success"
    mock_tcp_client.request_cloud_refinement.assert_called_once()
    request_payload = mock_tcp_client.request_cloud_refinement.call_args[0][0]
    assert isinstance(request_payload, LocalRequestCloudRefinementPayload)
    assert request_payload.local_model_draft_result == local_llm_output
    mock_tcp_client.send_confident_result_notification.assert_not_called()

@pytest.mark.asyncio
async def test_process_user_request_low_confidence_cloud_failure_fallback(task_orchestrator, mock_vllm_service, mock_confidence_service, mock_tcp_client):
    user_prompt = "Why is the sky blue?"
    local_llm_output = "Because."
    
    mock_vllm_service.generate_response.return_value = {"choices": [{"message": {"content": local_llm_output}}]}
    mock_confidence_service.assess.return_value = ConfidenceResult(needs_refinement=True, score=0.1, keywords_found=[], details={})
    mock_tcp_client.request_cloud_refinement.return_value = CloudRefinementResponseToLocalPayload(
        status="error", error_message="Cloud model overload"
    )

    result = await task_orchestrator.process_user_request_full_flow(user_prompt)

    assert result["result_text"] == local_llm_output # Fallback
    assert result["source"] == "local_fallback_cloud_failure"
    assert "cloud_response" in result["details"]["stages"][-1]

@pytest.mark.asyncio
async def test_process_user_request_low_confidence_cloud_timeout_fallback(task_orchestrator, mock_vllm_service, mock_confidence_service, mock_tcp_client):
    user_prompt = "Recipe for disaster."
    local_llm_output = "Step 1: ..."
    mock_vllm_service.generate_response.return_value = {"choices": [{"message": {"content": local_llm_output}}]}
    mock_confidence_service.assess.return_value = ConfidenceResult(needs_refinement=True, score=0.1, keywords_found=[], details={})
    mock_tcp_client.request_cloud_refinement.side_effect = TCPClientTimeoutError("Cloud request timed out")

    result = await task_orchestrator.process_user_request_full_flow(user_prompt)

    assert result["result_text"] == local_llm_output # Fallback
    assert result["source"] == "local_fallback_cloud_timeout"
    assert result["details"]["stages"][-1]["status"] == "timeout"

@pytest.mark.asyncio
async def test_process_user_request_vllm_failure(task_orchestrator, mock_vllm_service):
    user_prompt = "This will fail."
    mock_vllm_service.generate_response.side_effect = VLLMServiceError("vLLM is down")

    result = await task_orchestrator.process_user_request_full_flow(user_prompt)

    assert result["result_text"] is None
    assert result["source"] == "error_orchestration"
    assert "Local LLM generation failed: vLLM is down" in result["error"]
    assert result["details"]["stages"][0]["status"] == "error"

# --- Tests for process_incoming_tcp_message ---
@pytest.mark.asyncio
async def test_process_tcp_execute_owl_task_success(task_orchestrator, mock_owl_agent_service):
    task_id = str(uuid.uuid4())
    agent_task_desc = "Summarize this document."
    owl_result_data = {"agent_outcome": "Summary complete.", "status": "success"}
    mock_owl_agent_service.execute_task.return_value = owl_result_data

    cmd_details = ExecuteOwlTaskDetails(agent_task_description=agent_task_desc)
    cmd_payload = RemoteCommandToLocalPayload(command_action="execute_owl_task", command_details=cmd_details.model_dump())
    incoming_msg = BaseMessage(task_id=task_id, message_type="remote_command_to_local", payload=cmd_payload.model_dump())

    response_payload_content = await task_orchestrator.process_incoming_tcp_message(incoming_msg.model_dump(), MagicMock()) # Mock writer
    
    assert response_payload_content is not None
    response = LocalResponseToRemotePayload(**response_payload_content)
    assert response.status == "success"
    assert response.data == owl_result_data
    mock_owl_agent_service.execute_task.assert_called_once_with(task_description=agent_task_desc, agent_config_override=None)

@pytest.mark.asyncio
async def test_process_tcp_query_local_model_direct_success(task_orchestrator, mock_vllm_service):
    task_id = str(uuid.uuid4())
    prompt = "What is 2+2?"
    vllm_output = "2+2 is 4."
    mock_vllm_service.generate_response.return_value = {"choices": [{"message": {"content": vllm_output}}], "usage": {}}

    cmd_details = QueryLocalModelDirectDetails(prompt=prompt)
    cmd_payload = RemoteCommandToLocalPayload(command_action="query_local_model_direct", command_details=cmd_details.model_dump())
    incoming_msg = BaseMessage(task_id=task_id, message_type="remote_command_to_local", payload=cmd_payload.model_dump())

    response_payload_content = await task_orchestrator.process_incoming_tcp_message(incoming_msg.model_dump(), MagicMock())

    assert response_payload_content is not None
    response = LocalResponseToRemotePayload(**response_payload_content)
    assert response.status == "success"
    assert response.data["generated_text"] == vllm_output
    mock_vllm_service.generate_response.assert_called_once_with(prompt=prompt, params=cmd_details.vllm_params)

@pytest.mark.asyncio
async def test_process_tcp_get_local_status(task_orchestrator, mock_settings, mock_vllm_service, mock_owl_agent_service, mock_tcp_client):
    task_id = str(uuid.uuid4())
    cmd_payload = RemoteCommandToLocalPayload(command_action="get_local_status")
    incoming_msg = BaseMessage(task_id=task_id, message_type="remote_command_to_local", payload=cmd_payload.model_dump())

    response_payload_content = await task_orchestrator.process_incoming_tcp_message(incoming_msg.model_dump(), MagicMock())

    assert response_payload_content is not None
    response = LocalResponseToRemotePayload(**response_payload_content)
    assert response.status == "success"
    assert response.data["local_server_id"] == mock_settings.local_server_id
    assert response.data["vllm_service_status"] == "healthy"
    assert response.data["owl_agent_status"] == {"status": "healthy"}
    mock_vllm_service.check_health.assert_called_once()
    mock_owl_agent_service.check_agent_health.assert_called_once()

@pytest.mark.asyncio
async def test_process_tcp_unknown_command_action(task_orchestrator):
    task_id = str(uuid.uuid4())
    cmd_payload = RemoteCommandToLocalPayload(command_action="do_magic", command_details={})
    # Pydantic will raise validation error for unknown command_action in RemoteCommandToLocalPayload itself.
    # So, this test needs to bypass that or test the model validation separately.
    # Assuming the model allows it for this test (e.g. by mocking validation or using a dict):
    raw_payload = {"command_action": "do_magic", "command_details": {}}
    incoming_msg = BaseMessage(task_id=task_id, message_type="remote_command_to_local", payload=raw_payload)

    response_payload_content = await task_orchestrator.process_incoming_tcp_message(incoming_msg.model_dump(), MagicMock())

    assert response_payload_content is not None
    response = LocalResponseToRemotePayload(**response_payload_content)
    assert response.status == "error"
    assert "Unknown command_action: do_magic" in response.error_message

@pytest.mark.asyncio
async def test_process_tcp_unhandled_message_type(task_orchestrator):
    task_id = str(uuid.uuid4())
    incoming_msg = BaseMessage(task_id=task_id, message_type="some_other_type", payload={"data": 1})
    response_payload_content = await task_orchestrator.process_incoming_tcp_message(incoming_msg.model_dump(), MagicMock())
    assert response_payload_content is None # No direct response for unhandled types

# --- Tests for process_batch_prompts_concurrently ---
@pytest.mark.asyncio
async def test_process_batch_prompts_success(task_orchestrator, mock_vllm_service):
    prompts = ["Prompt 1", "Prompt 2"]
    mock_vllm_service.generate_response.side_effect = [
        {"choices": [{"message": {"content": "Response 1"}}], "usage": {}},
        {"choices": [{"message": {"content": "Response 2"}}], "usage": {}}
    ]

    results = await task_orchestrator.process_batch_prompts_concurrently(prompts)

    assert len(results) == 2
    assert results[0]["status"] == "success"
    assert results[0]["generated_text"] == "Response 1"
    assert results[1]["status"] == "success"
    assert results[1]["generated_text"] == "Response 2"
    assert mock_vllm_service.generate_response.call_count == 2

@pytest.mark.asyncio
async def test_process_batch_prompts_partial_failure(task_orchestrator, mock_vllm_service):
    prompts = ["Prompt A", "Prompt B"]
    mock_vllm_service.generate_response.side_effect = [
        {"choices": [{"message": {"content": "Response A"}}], "usage": {}},
        VLLMServiceError("Failed for B")
    ]

    results = await task_orchestrator.process_batch_prompts_concurrently(prompts)

    assert len(results) == 2
    assert results[0]["status"] == "success"
    assert results[0]["generated_text"] == "Response A"
    assert results[1]["status"] == "error"
    assert "Failed for B" in results[1]["error_message"]

@pytest.mark.asyncio
async def test_process_batch_prompts_empty_list(task_orchestrator, mock_vllm_service):
    results = await task_orchestrator.process_batch_prompts_concurrently([])
    assert results == []
    mock_vllm_service.generate_response.assert_not_called()

