import pytest
import asyncio
import json
from unittest.mock import patch, AsyncMock, MagicMock

from local_server.core.config import AppSettings, RemoteServerSettings
from local_server.communication.tcp_server import start_tcp_server
from local_server.communication.protocol_models import BaseMessage

SERVER_ID = "test_server_01"
TEST_HOST = "127.0.0.1"
TEST_PORT = 9998 # Different from client test port

@pytest.fixture
def mock_settings():
    remote_settings = RemoteServerSettings(host=TEST_HOST, command_port=TEST_PORT)
    app_settings = AppSettings(remote_server=remote_settings, local_server_id=SERVER_ID)
    # Patch settings used by tcp_server module if it imports settings directly
    with patch("local_server.communication.tcp_server.settings", app_settings):
        yield app_settings

@pytest.fixture
async def mock_message_handler():
    handler = AsyncMock(return_value=None) # Default: no response payload
    return handler

@pytest.fixture
async def running_tcp_server(mock_settings, mock_message_handler):
    """Starts the TCP server and yields, then shuts it down."""
    server_task = asyncio.create_task(
        start_tcp_server(
            host=TEST_HOST,
            port=TEST_PORT,
            message_handler=mock_message_handler,
            server_id=SERVER_ID
        )
    )
    # Allow server to start up
    await asyncio.sleep(0.1)
    
    yield {"task": server_task, "handler": mock_message_handler}
    
    # Shutdown sequence
    print("Test: Shutting down TCP server fixture...")
    if not server_task.done():
        # Simulate the shutdown signal if the server uses one, or directly cancel.
        # The current start_tcp_server doesn't have an explicit external shutdown event mechanism
        # other than cancelling its main task. So, we cancel it.
        server_task.cancel()
        try:
            await asyncio.wait_for(server_task, timeout=2.0)  # Use a fixed timeout value
        except asyncio.CancelledError:
            print("Test: Server task cancelled as expected.")
        except asyncio.TimeoutError:
            print("Test: Server task did not shut down in time.")
        except Exception as e:
            print(f"Test: Error during server task shutdown: {e}")
    print("Test: TCP server fixture shutdown complete.")

@pytest.mark.asyncio
async def test_tcp_server_starts_and_accepts_connection(running_tcp_server):
    try:
        reader, writer = await asyncio.open_connection(TEST_HOST, TEST_PORT)
        assert writer is not None
        print("TestClient: Connected to server.")
        writer.close()
        await writer.wait_closed()
        print("TestClient: Connection closed.")
    except ConnectionRefusedError:
        pytest.fail("Server did not accept connection.")
    # Server shutdown is handled by the fixture

@pytest.mark.asyncio
async def test_tcp_server_receives_message_and_calls_handler(running_tcp_server):
    mock_handler = running_tcp_server["handler"]
    reader, writer = await asyncio.open_connection(TEST_HOST, TEST_PORT)

    test_payload = {"data": "hello server"}
    test_message = BaseMessage(message_type="client_greeting", payload=test_payload)
    message_json = test_message.model_dump_json()

    writer.write(message_json.encode() + b"\n")
    await writer.drain()
    print(f"TestClient: Sent: {message_json}")

    await asyncio.sleep(0.1) # Give server time to process

    mock_handler.assert_called_once()
    args, kwargs = mock_handler.call_args
    received_dict = args[0]
    client_writer = args[1]
    
    assert client_writer is not None # Ensure writer is passed to handler
    assert received_dict["message_type"] == "client_greeting"
    assert received_dict["payload"] == test_payload
    assert received_dict["task_id"] == test_message.task_id

    writer.close()
    await writer.wait_closed()

@pytest.mark.asyncio
async def test_tcp_server_sends_response_from_handler(running_tcp_server):
    response_payload_content = {"status": "ok", "reply": "got it"}
    # Configure handler to return this payload
    running_tcp_server["handler"].return_value = response_payload_content

    reader, writer = await asyncio.open_connection(TEST_HOST, TEST_PORT)

    request_message = BaseMessage(message_type="request_data", payload={"id": 123})
    writer.write(request_message.model_dump_json().encode() + b"\n")
    await writer.drain()
    print(f"TestClient: Sent request: {request_message.model_dump_json()}")

    # Read response from server
    response_data = await reader.readline()
    response_str = response_data.decode().strip()
    print(f"TestClient: Received response: {response_str}")
    
    response_msg = BaseMessage.model_validate_json(response_str)
    assert response_msg.message_type == "local_response_to_remote" # Default type for handler responses
    assert response_msg.task_id == request_message.task_id # Should echo task_id
    assert response_msg.payload == response_payload_content

    writer.close()
    await writer.wait_closed()

@pytest.mark.asyncio
async def test_tcp_server_handles_client_disconnect(running_tcp_server, caplog):
    reader, writer = await asyncio.open_connection(TEST_HOST, TEST_PORT)
    peername = writer.get_extra_info("peername")
    print(f"TestClient: Connected as {peername}")

    # Client abruptly closes connection
    writer.close()
    await writer.wait_closed()
    print(f"TestClient: Closed connection {peername}")

    await asyncio.sleep(0.1) # Give server time to process disconnect
    # Check logs for disconnect message
    assert f"Client {peername} disconnected." in caplog.text or f"Connection closed for {peername}" in caplog.text

@pytest.mark.asyncio
async def test_tcp_server_handles_invalid_json(running_tcp_server, caplog):
    reader, writer = await asyncio.open_connection(TEST_HOST, TEST_PORT)
    peername = writer.get_extra_info("peername")

    invalid_json_message = "this is not json\n"
    writer.write(invalid_json_message.encode())
    await writer.drain()
    print(f"TestClient: Sent invalid JSON: {invalid_json_message.strip()}")

    await asyncio.sleep(0.1)
    assert f"Error decoding JSON from client {peername}" in caplog.text
    
    # Server should not call handler for invalid JSON
    running_tcp_server["handler"].assert_not_called()

    writer.close()
    await writer.wait_closed()

@pytest.mark.asyncio
async def test_tcp_server_handles_incomplete_json_then_valid(running_tcp_server):
    mock_handler = running_tcp_server["handler"]
    reader, writer = await asyncio.open_connection(TEST_HOST, TEST_PORT)

    incomplete_part1 = "{\"message_type\": \"partial\", "
    writer.write(incomplete_part1.encode())
    await writer.drain()
    await asyncio.sleep(0.05) # Send quickly
    
    # Handler should not be called yet
    mock_handler.assert_not_called()

    complete_part2 = "\"payload\": {\"data\": \"done\"}}\n"
    writer.write(complete_part2.encode())
    await writer.drain()
    print(f"TestClient: Sent complete message in two parts.")

    await asyncio.sleep(0.1)
    mock_handler.assert_called_once()
    args, _ = mock_handler.call_args
    received_dict = args[0]
    assert received_dict["message_type"] == "partial"
    assert received_dict["payload"] == {"data": "done"}

    writer.close()
    await writer.wait_closed()

@pytest.mark.asyncio
async def test_tcp_server_max_clients(mock_settings, mock_message_handler, caplog):
    # This test is conceptual as the current server doesn't enforce MAX_CLIENTS strictly in a way
    # that rejects connections beyond a limit. It accepts all and handles them concurrently.
    # If MAX_CLIENTS were implemented (e.g., via a semaphore in handle_connection), this test would be different.
    # For now, we just test multiple clients can connect.
    num_clients = 5
    clients = []
    server_task = asyncio.create_task(
        start_tcp_server(TEST_HOST, TEST_PORT, mock_message_handler, SERVER_ID)
    )
    await asyncio.sleep(0.1)

    try:
        for i in range(num_clients):
            r, w = await asyncio.open_connection(TEST_HOST, TEST_PORT)
            clients.append((r, w))
            print(f"TestClient {i}: Connected")
        assert len(clients) == num_clients
    finally:
        for r, w in clients:
            w.close()
            await w.wait_closed()
        server_task.cancel()
        try: await server_task
        except asyncio.CancelledError: pass

