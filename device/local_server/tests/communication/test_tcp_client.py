import pytest
import asyncio
import json
from unittest.mock import patch, AsyncMock, MagicMock

from local_server.core.config import AppSettings, RemoteServerSettings
from local_server.communication.tcp_client import TCPRemoteClient, TCPClientError, TCPClientConnectionError, TCPClientTimeoutError
from local_server.communication.protocol_models import BaseMessage, HeartbeatPayload, LocalRequestCloudRefinementPayload, CloudRefinementResponseToLocalPayload

CLIENT_ID = "test_client_01"
TEST_HOST = "127.0.0.1"
TEST_PORT = 9999

@pytest.fixture
def mock_settings():
    remote_settings = RemoteServerSettings(
        host=TEST_HOST, 
        command_port=TEST_PORT, 
        cloud_request_timeout_seconds=2,
        heartbeat_interval_seconds=30,
        tcp_client_reconnect_delay_seconds=1,
        tcp_client_max_reconnect_delay_seconds=5
    )
    app_settings = AppSettings(remote_server=remote_settings, local_server_id=CLIENT_ID)
    with patch("local_server.communication.tcp_client.settings", app_settings):
        yield app_settings

@pytest.fixture
async def mock_tcp_server():
    """A simple mock TCP server for testing client connections."""
    server_store = {"received_data": [], "responses_to_send": [], "server_task": None, "clients": []}

    async def handle_connection(reader, writer):
        server_store["clients"].append(writer)
        addr = writer.get_extra_info("peername")
        print(f"MockServer: Connection from {addr}")
        try:
            while True:
                data = await reader.readline()
                if not data:
                    print(f"MockServer: Client {addr} disconnected")
                    break
                message = data.decode().strip()
                print(f"MockServer: Received from {addr}: {message}")
                server_store["received_data"].append(message)
                
                # Send predefined responses if any
                if server_store["responses_to_send"]:
                    response_to_send = server_store["responses_to_send"].pop(0)
                    print(f"MockServer: Sending to {addr}: {response_to_send}")
                    writer.write(response_to_send.encode() + b"\n")
                    await writer.drain()
        except ConnectionResetError:
            print(f"MockServer: Client {addr} reset connection.")
        except Exception as e:
            print(f"MockServer: Error handling client {addr}: {e}")
        finally:
            if writer in server_store["clients"]:
                server_store["clients"].remove(writer)
            writer.close()
            await writer.wait_closed()
            print(f"MockServer: Connection with {addr} closed.")

    server = await asyncio.start_server(handle_connection, TEST_HOST, TEST_PORT)
    server_store["server_task"] = asyncio.create_task(server.serve_forever())
    print(f"MockServer: Listening on {TEST_HOST}:{TEST_PORT}")
    
    yield server_store # Provide the store for tests to interact with
    
    print("MockServer: Shutting down...")
    if server_store["server_task"] and not server_store["server_task"].done():
        server_store["server_task"].cancel()
        try:
            await server_store["server_task"]
        except asyncio.CancelledError:
            pass
    server.close()
    await server.wait_closed()
    print("MockServer: Shutdown complete.")

@pytest.fixture
async def tcp_client(mock_settings):
    client = TCPRemoteClient(
        host=TEST_HOST,
        port=TEST_PORT,
        client_id=CLIENT_ID,
        on_unsolicited_message_callback=AsyncMock(),
        on_disconnect_callback=AsyncMock()
    )
    yield client
    # Ensure client is closed after test, even if test fails
    if client.is_connected or client._receive_loop_task or client._heartbeat_task:
         await client.close()

@pytest.mark.asyncio
async def test_tcp_client_connect_success(tcp_client, mock_tcp_server):
    assert await tcp_client.connect() is True
    assert tcp_client.is_connected
    assert tcp_client.reader is not None
    assert tcp_client.writer is not None
    assert tcp_client._receive_loop_task is not None
    await tcp_client.close() # Cleanly close for this test

@pytest.mark.asyncio
async def test_tcp_client_connect_fail_refused(tcp_client):
    # No server running on a different port
    client_fail = TCPRemoteClient(host=TEST_HOST, port=TEST_PORT + 1, client_id="fail_client")
    assert await client_fail.connect() is False
    assert not client_fail.is_connected
    await client_fail.close()

@pytest.mark.asyncio
async def test_tcp_client_send_heartbeat(tcp_client, mock_tcp_server, mock_settings):
    await tcp_client.connect()
    assert tcp_client.is_connected
    
    hb_payload = HeartbeatPayload(local_server_id=CLIENT_ID, status="ok", model_name="test_model")
    assert await tcp_client.send_heartbeat(hb_payload) is True
    
    await asyncio.sleep(0.1) # Give server time to process
    assert len(mock_tcp_server["received_data"]) == 1
    received_msg_str = mock_tcp_server["received_data"][0]
    received_msg = json.loads(received_msg_str)
    assert received_msg["message_type"] == "heartbeat"
    assert received_msg["payload"]["local_server_id"] == CLIENT_ID
    assert received_msg["payload"]["status"] == "ok"
    await tcp_client.close()

@pytest.mark.asyncio
async def test_tcp_client_receive_message_unsolicited(tcp_client, mock_tcp_server):
    await tcp_client.connect()
    assert tcp_client.is_connected

    unsolicited_msg_payload = {"info": "server broadcast"}
    unsolicited_msg = BaseMessage(task_id="server_task_1", message_type="server_notification", payload=unsolicited_msg_payload)
    mock_tcp_server["responses_to_send"].append(unsolicited_msg.model_dump_json())
    
    # Trigger a send from client to make server process its queue (or just wait for server to send)
    # For this test, we assume the server sends it proactively after connection or upon some event.
    # We need to ensure the client's receive loop is running and processes it.
    # The mock_tcp_server will send it when the client connects and the server's handle_connection gets to it.
    # However, the current mock_tcp_server sends only after receiving something.
    # Let's modify mock_tcp_server to send immediately if there's something in responses_to_send upon connection.
    # For now, let's send a dummy message from client to trigger server's send.
    await tcp_client.send_heartbeat() # Dummy send to kick server
    await asyncio.sleep(0.2) # Allow time for message exchange

    tcp_client.on_unsolicited_message_callback.assert_called_once()
    called_arg = tcp_client.on_unsolicited_message_callback.call_args[0][0]
    assert called_arg["message_type"] == "server_notification"
    assert called_arg["payload"] == unsolicited_msg_payload
    await tcp_client.close()

@pytest.mark.asyncio
async def test_tcp_client_request_cloud_refinement_success(tcp_client, mock_tcp_server, mock_settings):
    await tcp_client.connect()
    assert tcp_client.is_connected

    request_data = LocalRequestCloudRefinementPayload(
        original_user_prompt="prompt", 
        local_model_draft_result="draft",
        confidence_assessment=MagicMock() # Mocked for simplicity
    )
    
    response_payload = CloudRefinementResponseToLocalPayload(status="success", refined_result="refined_text")
    # The server needs to send back a BaseMessage wrapping this payload, with the correct task_id
    
    # We need to capture the task_id client generates to craft the server response
    original_send_message_internal = tcp_client._send_message_internal
    sent_task_id = None
    async def wrapped_send(message: BaseMessage):
        nonlocal sent_task_id
        if message.message_type == "local_request_cloud_refinement":
            sent_task_id = message.task_id
        return await original_send_message_internal(message)
    
    with patch.object(tcp_client, "_send_message_internal", new=wrapped_send):
        # Start the request task
        response_task = asyncio.create_task(tcp_client.request_cloud_refinement(request_data))
        
        await asyncio.sleep(0.1) # Allow send to happen and task_id to be captured
        assert sent_task_id is not None
        
        # Now, queue the server's response
        server_response_msg = BaseMessage(task_id=sent_task_id, message_type="cloud_refinement_response", payload=response_payload.model_dump())
        mock_tcp_server["responses_to_send"].append(server_response_msg.model_dump_json())
        
        # Await the client's request method
        cloud_response = await response_task

    assert cloud_response is not None
    assert cloud_response.status == "success"
    assert cloud_response.refined_result == "refined_text"
    assert not tcp_client._pending_requests # Should be cleared
    await tcp_client.close()

@pytest.mark.asyncio
async def test_tcp_client_request_cloud_refinement_timeout(tcp_client, mock_tcp_server, mock_settings):
    await tcp_client.connect()
    assert tcp_client.is_connected

    request_data = LocalRequestCloudRefinementPayload(original_user_prompt="p", local_model_draft_result="d", confidence_assessment=MagicMock())
    
    # Server will not send a response for this request
    with pytest.raises(TCPClientTimeoutError):
        await tcp_client.request_cloud_refinement(request_data, timeout=0.1) # Short timeout
    
    assert not tcp_client._pending_requests # Should be cleared after timeout
    await tcp_client.close()

@pytest.mark.asyncio
async def test_tcp_client_handle_disconnection(tcp_client, mock_tcp_server):
    await tcp_client.connect()
    assert tcp_client.is_connected

    # Simulate server closing the connection by stopping the mock server
    # (More directly, the mock_tcp_server's client handler could close the writer)
    # For this test, let's assume the client's writer is closed by the server.
    if mock_tcp_server["clients"]:
        server_writer = mock_tcp_server["clients"][0]
        server_writer.close()
        await server_writer.wait_closed()
    
    await asyncio.sleep(0.2) # Give client's receive loop time to detect closure

    assert not tcp_client.is_connected
    tcp_client.on_disconnect_callback.assert_called_once()
    # Check if pending requests are cleared (if any were made)
    # For this test, no pending requests were made before disconnect.
    await tcp_client.close()

@pytest.mark.asyncio
async def test_tcp_client_maintain_connection_loop_and_heartbeat(tcp_client, mock_tcp_server, mock_settings, caplog):
    # This is a more complex test for the interaction of maintain_connection and heartbeat
    # We won't connect initially, let maintain_connection_loop do it.
    
    maintain_task = asyncio.create_task(tcp_client.maintain_connection_loop())
    # Allow time for initial connection attempt
    await asyncio.sleep(mock_settings.remote_server.tcp_client_reconnect_delay_seconds + 0.2)
    assert tcp_client.is_connected

    # Start heartbeat loop (it should send a heartbeat since connected)
    await tcp_client.start_heartbeat_loop(vllm_health_check_func=AsyncMock(return_value=True), active_tasks_func=AsyncMock(return_value=0))
    await asyncio.sleep(0.1) # Allow heartbeat to be created and potentially one send
    
    # Check if a heartbeat was sent (mock_tcp_server should have received it)
    # This part is tricky because heartbeat interval might be long.
    # Let's shorten interval for test or trigger heartbeat manually for verification.
    # For now, we assume the first heartbeat might be sent quickly or we test send_heartbeat directly.
    # The start_heartbeat_loop itself doesn't send immediately, it waits for the interval.
    # So, let's check if the task is running.
    assert tcp_client._heartbeat_task is not None
    assert not tcp_client._heartbeat_task.done()

    # Simulate a disconnect
    if mock_tcp_server["clients"]:
        server_writer = mock_tcp_server["clients"][0]
        server_writer.close()
        await server_writer.wait_closed()
    
    await asyncio.sleep(0.2) # Let client detect disconnect
    assert not tcp_client.is_connected
    tcp_client.on_disconnect_callback.assert_called()

    # maintain_connection_loop should try to reconnect
    # Check logs for reconnection attempts
    await asyncio.sleep(mock_settings.remote_server.tcp_client_reconnect_delay_seconds + 0.5)
    assert tcp_client.is_connected # Should have reconnected

    # Clean up
    maintain_task.cancel()
    await tcp_client.close() # This will also cancel heartbeat task
    try: await maintain_task
    except asyncio.CancelledError: pass

@pytest.mark.asyncio
async def test_tcp_client_shutdown_cancels_tasks(tcp_client, mock_tcp_server):
    await tcp_client.connect()
    assert tcp_client.is_connected
    maintain_task = asyncio.create_task(tcp_client.maintain_connection_loop())
    await tcp_client.start_heartbeat_loop()
    
    assert tcp_client._receive_loop_task and not tcp_client._receive_loop_task.done()
    assert tcp_client._heartbeat_task and not tcp_client._heartbeat_task.done()
    
    await tcp_client.close() # This should trigger shutdown
    
    assert tcp_client._shutdown_event.is_set()
    # Tasks should be cancelled or completed
    # Due to the way tasks are awaited in close/handle_disconnection, they should be done.
    assert tcp_client._receive_loop_task is None or tcp_client._receive_loop_task.done()
    assert tcp_client._heartbeat_task.done() # Heartbeat is explicitly cancelled and awaited in close
    
    maintain_task.cancel() # Cancel the test's maintain_task
    try: await maintain_task
    except asyncio.CancelledError: pass

