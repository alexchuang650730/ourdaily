import asyncio
import json
import logging
import uuid
from typing import Dict, Any, Optional, Callable, Awaitable

from ..core.config import settings # Assuming settings are available
from .protocol_models import BaseMessage # For parsing and constructing messages

logger = logging.getLogger(__name__) 

# Define a type for the message handler callback that the server will use
# It receives the parsed message dictionary and the StreamWriter for direct responses if needed.
# It should return an Optional dictionary, which, if provided, is the PAYLOAD for a response message.
MessageHandlerType = Callable[[Dict[str, Any], asyncio.StreamWriter], Awaitable[Optional[Dict[str, Any]]]]

async def handle_client_connection(
    reader: asyncio.StreamReader, 
    writer: asyncio.StreamWriter, 
    message_handler: MessageHandlerType,
    server_id: str # To identify which server instance is logging
):
    peername = writer.get_extra_info("peername")
    connection_session_id = str(uuid.uuid4()) # Unique ID for this specific client connection session
    logger.info(f"TCPServer ({server_id}): Accepted connection from {peername} (Session: {connection_session_id})")
    message_buffer = ""

    try:
        while True:
            try:
                data = await reader.read(4096) # Read a chunk of data
                if not data:
                    logger.info(f"TCPServer ({server_id}): Client {peername} (Session: {connection_session_id}) disconnected (received empty data).")
                    break
                
                message_buffer += data.decode("utf-8")
                
                # Process all newline-terminated messages in the buffer
                while "\n" in message_buffer:
                    message_str, message_buffer = message_buffer.split("\n", 1)
                    message_str = message_str.strip()
                    if not message_str: # Skip empty lines after strip
                        continue

                    logger.debug(f"TCPServer ({server_id}): Received from {peername} (Session: {connection_session_id}): {message_str}")
                    incoming_dict: Optional[Dict[str, Any]] = None
                    try:
                        incoming_dict = json.loads(message_str)
                        # Basic validation using BaseMessage can be done here or within the handler
                        # For now, assume handler will validate further or use Pydantic models.
                        
                        # Pass the raw dict and writer to the message handler (e.g., TaskOrchestrator)
                        # The handler is responsible for business logic and determining the response payload.
                        response_payload_content = await message_handler(incoming_dict, writer)

                        if response_payload_content is not None:
                            # If handler returns a payload, construct and send a standard response message.
                            # The handler should ensure the original task_id is included if it's a direct response.
                            response_task_id = incoming_dict.get("task_id", str(uuid.uuid4()))
                            
                            # Assume response_payload_content is the dict for the 'payload' field of BaseMessage
                            # and the message_type for response is standard (e.g. "local_response_to_remote")
                            # unless the handler specifies a different message_type within response_payload_content itself.
                            
                            response_message_type = response_payload_content.pop("message_type_override", "local_response_to_remote")

                            response_msg_obj = BaseMessage(
                                task_id=response_task_id, 
                                message_type=response_message_type,
                                payload=response_payload_content
                            )
                            response_json = response_msg_obj.model_dump_json()
                            logger.debug(f"TCPServer ({server_id}): Sending to {peername} (Session: {connection_session_id}): {response_json}")
                            writer.write(response_json.encode("utf-8") + b"\n")
                            await writer.drain()
                        # If response_payload_content is None, handler might have sent a response directly or no response was needed.

                    except json.JSONDecodeError as e_json:
                        logger.error(f"TCPServer ({server_id}): Invalid JSON from {peername} (Session: {connection_session_id}): " +
                                     f"Data: \nRPT.Slice.Start------------------------------------------------------\n{message_str}\nRPT.Slice.End--------------------------------------------------------\n Error: {e_json}")
                        # Send an error response if possible
                        error_task_id = str(uuid.uuid4())
                        if incoming_dict and "task_id" in incoming_dict:
                            error_task_id = incoming_dict["task_id"]
                        error_response = BaseMessage(
                            task_id=error_task_id, 
                            message_type="error_response", 
                            payload={"error": "Invalid JSON format received", "details": str(e_json)}
                        )
                        try:
                            writer.write(error_response.model_dump_json().encode("utf-8") + b"\n")
                            await writer.drain()
                        except Exception as write_err:
                            logger.error(f"TCPServer ({server_id}): Failed to send JSON error response to {peername}: {write_err}")
                    except Exception as e_handler: # Catch errors from message_handler or Pydantic validation
                        logger.error(f"TCPServer ({server_id}): Error processing message from {peername} (Session: {connection_session_id}): {e_handler}", exc_info=True)
                        error_task_id = str(uuid.uuid4())
                        if incoming_dict and "task_id" in incoming_dict:
                            error_task_id = incoming_dict["task_id"]
                        error_response = BaseMessage(
                            task_id=error_task_id,
                            message_type="error_response",
                            payload={"error": "Internal server error during message processing", "details": str(e_handler)}
                        )
                        try:
                            writer.write(error_response.model_dump_json().encode("utf-8") + b"\n")
                            await writer.drain()
                        except Exception as write_err:
                            logger.error(f"TCPServer ({server_id}): Failed to send internal error response to {peername}: {write_err}")
                        # Depending on error, might continue or break. For now, continue.
            
            except ConnectionResetError:
                logger.info(f"TCPServer ({server_id}): Client {peername} (Session: {connection_session_id}) reset connection.")
                break 
            except asyncio.IncompleteReadError:
                logger.info(f"TCPServer ({server_id}): Incomplete read from {peername} (Session: {connection_session_id}), connection likely closed by client.")
                break
            except Exception as e_conn_loop: # Catch broader errors in the connection loop itself
                logger.error(f"TCPServer ({server_id}): Error in connection loop for {peername} (Session: {connection_session_id}): {e_conn_loop}", exc_info=True)
                break # Critical error in connection handling, terminate this client's loop
    
    except Exception as e_outer:
        # This catches errors if the loop itself fails catastrophically (e.g., before even reading)
        logger.error(f"TCPServer ({server_id}): Unhandled exception in connection handler for {peername} (Session: {connection_session_id}): {e_outer}", exc_info=True)
    finally:
        logger.info(f"TCPServer ({server_id}): Closing connection with {peername} (Session: {connection_session_id})")
        if writer and not writer.is_closing():
            try:
                writer.close()
                await writer.wait_closed()
            except Exception as e_close:
                logger.error(f"TCPServer ({server_id}): Error during writer close for {peername} (Session: {connection_session_id}): {e_close}")

async def start_tcp_server(
    host: str, 
    port: int, 
    message_handler: MessageHandlerType,
    server_id: str = "default_server"
):
    server: Optional[asyncio.AbstractServer] = None
    try:
        server = await asyncio.start_server(
            lambda r, w: handle_client_connection(r, w, message_handler, server_id),
            host,
            port
        )
        addr = server.sockets[0].getsockname() if server.sockets else (host, port)
        logger.info(f"TCPServer ({server_id}): Listening on {addr[0]}:{addr[1]}")

        async with server: # This ensures server.close() is called on exit
            await server.serve_forever()
    except OSError as e_os:
        logger.error(f"TCPServer ({server_id}): Failed to start on {host}:{port}. OS Error: {e_os}. Check if port is already in use or address is valid.", exc_info=True)
        # Propagate the error so the application knows the server didn't start
        raise
    except asyncio.CancelledError:
        logger.info(f"TCPServer ({server_id}): Serve forever task cancelled. Server shutting down.")
    except Exception as e_serve:
        logger.error(f"TCPServer ({server_id}): Serve forever loop encountered an unhandled error: {e_serve}", exc_info=True)
    finally:
        if server and server.is_serving():
            logger.info(f"TCPServer ({server_id}): Explicitly closing server.")
            server.close()
            await server.wait_closed()
        logger.info(f"TCPServer ({server_id}): Shutdown complete.")

# Example dummy message handler for testing (can be moved to a test file later)
# async def dummy_message_handler(message_dict: Dict[str, Any], writer: asyncio.StreamWriter) -> Optional[Dict[str, Any]]:
#     logger.info(f"DummyHandler: Received {message_dict}")
#     task_id = message_dict.get("task_id", "unknown_task")
#     await asyncio.sleep(0.01) # Simulate work
#     response_payload = {
#         "original_command_action": message_dict.get("payload", {}).get("command_action", "unknown_action"),
#         "status": "success",
#         "data": {"confirmation": f"Received your command for task {task_id}"}
#     }
#     return response_payload

