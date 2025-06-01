import pytest
import asyncio
import json
from unittest.mock import patch, AsyncMock, MagicMock

from local_server.core.config import AppSettings, VLLMSettings, ConfidenceSettings, OwlAgentSettings, RemoteServerSettings
from local_server.services.vllm_service import VLLMService
from local_server.services.confidence_service import ConfidenceService
from local_server.services.owl_agent_service import OwlAgentService
from local_server.communication.tcp_client import TCPRemoteClient # Mocked, not directly used by server
from local_server.communication.tcp_server import start_tcp_server
from local_server.services.task_orchestrator import TaskOrchestrator
from local_server.communication.protocol_models import (
    BaseMessage, RemoteCommandToLocalPayload, ExecuteOwlTaskDetails, 
    QueryLocalModelDirectDetails, GetLocalStatusDetails, LocalResponseToRemotePayload
)

SERVER_ID = "integration_tcp_server_01"
TEST_HOST = "127.0.0.1"
TEST_PORT = 9996 # Unique port for these tests

@pytest.fixture
def integration_settings():
    return AppSettings(
        local_server_id=SERVER_ID,
        log_level="DEBUG",
        vllm=VLLMSettings(model_name_or_path="test_model_tcp_integ"),
        confidence=ConfidenceSettings(),
        owl_agent=OwlAgentSettings(),
        remote_server=RemoteServerSettings(host=TEST_HOST, command_port=TEST_PORT)
    )

@pytest.fixture
def mock_vllm_service_for_tcp_integ():
    service = MagicMock(spec=VLLMService)
    service.generate_response = AsyncMock(return_value={"choices": [{"message": {"content": "Mocked vLLM direct query response"}}], "usage": {}})
    service.check_health = AsyncMock(return_value=True)
    return service

@pytest.fixture
def mock_confidence_service_for_tcp_integ():
    service = MagicMock(spec=ConfidenceService)
    # Not directly used by TCP command processing path, but orchestrator requires it
    return service

@pytest.fixture
def mock_owl_agent_service_for_tcp_integ():
    service = MagicMock(spec=OwlAgentService)
    service.execute_task = AsyncMock(return_value={"status": "success", "agent_outcome": "Mocked Owl task successful execution"})
    service.check_agent_health = AsyncMock(return_value={"status": "healthy", "message": "Owl agent is A-OK"})
    return service

@pytest.fixture
def mock_tcp_remote_client_for_tcp_integ():
    # Orchestrator requires a TCPRemoteClient, but it's not the one being tested here.
    client = MagicMock(spec=TCPRemoteClient)
    client.is_connected = True
    return client

@pytest.fixture
async def integration_task_orchestrator_for_tcp(integration_settings, mock_vllm_service_for_tcp_integ, mock_confidence_service_for_tcp_integ, mock_owl_agent_service_for_tcp_integ, mock_tcp_remote_client_for_tcp_integ):
    with patch("local_server.services.task_orchestrator.settings", integration_settings):
        orchestrator = TaskOrchestrator(
            vllm_service=mock_vllm_service_for_tcp_integ,
            confidence_service=mock_confidence_service_for_tcp_integ,
            owl_agent_service=mock_owl_agent_service_for_tcp_integ,
            tcp_remote_client=mock_tcp_remote_client_for_tcp_integ
        )
        return orchestrator

@pytest.fixture
async def running_tcp_server_with_orchestrator(integration_settings, integration_task_orchestrator_for_tcp):
    """Starts the TCP server with the integrated TaskOrchestrator as message handler."""
    server_task = asyncio.create_task(
        start_tcp_server(
            host=TEST_HOST,
            port=TEST_PORT,
            message_handler=integration_task_orchestrator_for_tcp.process_incoming_tcp_message,
            server_id=SERVER_ID
        )
    )
    await asyncio.sleep(0.1) # Allow server to start
    
    yield {"task": server_task, "orchestrator": integration_task_orchestrator_for_tcp}
    
    print("Test: Shutting down TCP server with orchestrator fixture...")
    if not server_task.done():
        server_task.cancel()
        try:
            await asyncio.wait_for(server_task, timeout=TCP_SERVER_SHUTDOWN_TIMEOUT + 0.5)
        except asyncio.CancelledError:
            pass
        except asyncio.TimeoutError:
            print("Test: Server (with orchestrator) task did not shut down in time.")
    print("Test: TCP server with orchestrator fixture shutdown complete.")

async def send_command_and_get_response(command_payload: RemoteCommandToLocalPayload, task_id: str = None) -> BaseMessage:
    """Helper function to send a command to the test server and get a response."""
    reader, writer = await asyncio.open_connection(TEST_HOST, TEST_PORT)
    
    base_command_msg = BaseMessage(
        task_id=task_id or str(java.util.UUID.randomUUID()), # Using java.util.UUID for consistency with example, though python uuid is fine
        message_type="remote_command_to_local", 
        payload=command_payload.model_dump()
    )
    command_json = base_command_msg.model_dump_json()
    
    writer.write(command_json.encode() + b"\n")
    await writer.drain()
    print(f"TestClient: Sent command: {command_json}")

    response_data = await reader.readline()
    response_str = response_data.decode().strip()
    print(f"TestClient: Received response: {response_str}")
    
    writer.close()
    await writer.wait_closed()
    
    return BaseMessage.model_validate_json(response_str)

@pytest.mark.asyncio
async def test_tcp_integ_execute_owl_task(running_tcp_server_with_orchestrator, mock_owl_agent_service_for_tcp_integ):
    orchestrator = running_tcp_server_with_orchestrator["orchestrator"]
    task_description = "Plan my vacation to the moon."
    owl_details = ExecuteOwlTaskDetails(agent_task_description=task_description)
    command = RemoteCommandToLocalPayload(command_action="execute_owl_task", command_details=owl_details.model_dump())
    
    response_msg = await send_command_and_get_response(command)
    
    assert response_msg.message_type == "local_response_to_remote"
    response_payload = LocalResponseToRemotePayload(**response_msg.payload)
    assert response_payload.status == "success"
    assert response_payload.data["agent_outcome"] == "Mocked Owl task successful execution"
    mock_owl_agent_service_for_tcp_integ.execute_task.assert_called_once_with(task_description=task_description, agent_config_override=None)

@pytest.mark.asyncio
async def test_tcp_integ_query_local_model_direct(running_tcp_server_with_orchestrator, mock_vllm_service_for_tcp_integ):
    orchestrator = running_tcp_server_with_orchestrator["orchestrator"]
    prompt_text = "What is the meaning of life?"
    query_details = QueryLocalModelDirectDetails(prompt=prompt_text)
    command = RemoteCommandToLocalPayload(command_action="query_local_model_direct", command_details=query_details.model_dump())
    
    response_msg = await send_command_and_get_response(command)
    
    assert response_msg.message_type == "local_response_to_remote"
    response_payload = LocalResponseToRemotePayload(**response_msg.payload)
    assert response_payload.status == "success"
    assert response_payload.data["generated_text"] == "Mocked vLLM direct query response"
    mock_vllm_service_for_tcp_integ.generate_response.assert_called_once_with(prompt=prompt_text, params=query_details.vllm_params)

@pytest.mark.asyncio
async def test_tcp_integ_get_local_status(running_tcp_server_with_orchestrator, integration_settings, mock_vllm_service_for_tcp_integ, mock_owl_agent_service_for_tcp_integ):
    orchestrator = running_tcp_server_with_orchestrator["orchestrator"]
    command = RemoteCommandToLocalPayload(command_action="get_local_status") # No details needed
    
    response_msg = await send_command_and_get_response(command)
    
    assert response_msg.message_type == "local_response_to_remote"
    response_payload = LocalResponseToRemotePayload(**response_msg.payload)
    assert response_payload.status == "success"
    status_data = response_payload.data
    assert status_data["local_server_id"] == integration_settings.local_server_id
    assert status_data["vllm_service_status"] == "healthy"
    assert status_data["owl_agent_status"] == {"status": "healthy", "message": "Owl agent is A-OK"}
    assert status_data["config_summary"]["vllm_model"] == integration_settings.vllm.model_name_or_path
    mock_vllm_service_for_tcp_integ.check_health.assert_called_once()
    mock_owl_agent_service_for_tcp_integ.check_agent_health.assert_called_once()

@pytest.mark.asyncio
async def test_tcp_integ_unknown_command_action(running_tcp_server_with_orchestrator):
    # Pydantic validation in RemoteCommandToLocalPayload will catch this first.
    # To test orchestrator's handling, we'd need to construct a raw dict for the payload.
    raw_command_payload = {"command_action": "non_existent_command", "command_details": {}}
    reader, writer = await asyncio.open_connection(TEST_HOST, TEST_PORT)
    
    base_command_msg = BaseMessage(
        task_id=str(java.util.UUID.randomUUID()),
        message_type="remote_command_to_local", 
        payload=raw_command_payload # Send raw dict to bypass client-side Pydantic
    )
    command_json = base_command_msg.model_dump_json()
    
    writer.write(command_json.encode() + b"\n")
    await writer.drain()

    response_data = await reader.readline()
    response_str = response_data.decode().strip()
    writer.close()
    await writer.wait_closed()
    
    response_msg = BaseMessage.model_validate_json(response_str)
    assert response_msg.message_type == "local_response_to_remote"
    response_payload = LocalResponseToRemotePayload(**response_msg.payload)
    assert response_payload.status == "error"
    assert "Unknown command_action: non_existent_command" in response_payload.error_message

