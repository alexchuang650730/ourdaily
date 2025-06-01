import asyncio
import json
from typing import Dict, Any, Optional, Callable, Awaitable
import logging
import uuid # Ensure uuid is imported

from ..core.config import settings
from .protocol_models import BaseMessage, HeartbeatPayload, LocalRequestCloudRefinementPayload, CloudRefinementResponseToLocalPayload, LocalConfidentResultNotificationPayload

logger = logging.getLogger(__name__) 

class TCPClientError(Exception):
    """Base exception for TCPClient errors."""
    pass

class TCPClientConnectionError(TCPClientError):
    """Raised when connection fails or is lost."""
    pass

class TCPClientTimeoutError(TCPClientError):
    """Raised on request timeout."""
    pass

class TCPRemoteClient:
    def __init__(self, 
                 host: str, 
                 port: int, 
                 client_id: str,
                 on_unsolicited_message_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
                 on_disconnect_callback: Optional[Callable[[], Awaitable[None]]] = None):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.is_connected = False
        self.on_unsolicited_message_callback = on_unsolicited_message_callback
        self.on_disconnect_callback = on_disconnect_callback
        self._receive_loop_task: Optional[asyncio.Task] = None
        self._pending_requests: Dict[str, asyncio.Future] = {}
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._connection_lock = asyncio.Lock()
        self._shutdown_event = asyncio.Event()

    async def connect(self) -> bool:
        async with self._connection_lock:
            if self.is_connected:
                return True
            if self._shutdown_event.is_set():
                logger.info(f"TCPClient ({self.client_id}): Shutdown in progress, not connecting.")
                return False
            try:
                logger.info(f"TCPClient ({self.client_id}): Attempting to connect to {self.host}:{self.port}")
                self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
                self.is_connected = True
                logger.info(f"TCPClient ({self.client_id}): Successfully connected to {self.host}:{self.port}")
                
                if self._receive_loop_task is None or self._receive_loop_task.done():
                    self._receive_loop_task = asyncio.create_task(self._receive_messages_loop())
                return True
            except ConnectionRefusedError as e:
                logger.warning(f"TCPClient ({self.client_id}): Connection refused by {self.host}:{self.port}. {e}")
            except asyncio.TimeoutError as e:
                logger.warning(f"TCPClient ({self.client_id}): Connection attempt to {self.host}:{self.port} timed out. {e}")
            except OSError as e: # Catch other OS-level errors like host not found
                logger.error(f"TCPClient ({self.client_id}): OS error connecting to {self.host}:{self.port}: {e}")
            except Exception as e:
                logger.error(f"TCPClient ({self.client_id}): Failed to connect to {self.host}:{self.port}: {e}", exc_info=True)
            
            self.is_connected = False # Ensure is_connected is false if any exception occurs
            return False

    async def _receive_messages_loop(self):
        logger.info(f"TCPClient ({self.client_id}): Receive loop started.")
        message_buffer = ""
        while self.is_connected and self.reader and not self._shutdown_event.is_set():
            try:
                data = await self.reader.read(4096) # Read a chunk of data
                if not data:
                    logger.warning(f"TCPClient ({self.client_id}): Connection closed by server (received empty data).")
                    await self._handle_disconnection()
                    break
                
                message_buffer += data.decode("utf-8")
                
                # Process all newline-terminated messages in the buffer
                while "\n" in message_buffer:
                    message_str, message_buffer = message_buffer.split("\n", 1)
                    message_str = message_str.strip()
                    if not message_str: # Skip empty lines after strip
                        continue
                    
                    logger.debug(f"TCPClient ({self.client_id}): Received raw message: {message_str}")
                    try:
                        message_dict = json.loads(message_str)
                        base_msg = BaseMessage(**message_dict) # Validate base structure

                        if base_msg.task_id in self._pending_requests:
                            future = self._pending_requests.pop(base_msg.task_id)
                            if not future.done():
                                future.set_result(base_msg.payload)
                            else:
                                logger.warning(f"TCPClient ({self.client_id}): Future for task {base_msg.task_id} was already done.")
                        elif self.on_unsolicited_message_callback:
                            asyncio.create_task(self.on_unsolicited_message_callback(message_dict))
                        else:
                            logger.warning(f"TCPClient ({self.client_id}): Received message for task_id {base_msg.task_id} but no pending request or unsolicited message callback.")
                    except json.JSONDecodeError as e_json:
                        logger.error(f"TCPClient ({self.client_id}): JSON decode error: {e_json} for data: {message_str}")
                    except Exception as e_msg_proc: # Catch errors from Pydantic validation or callback
                        logger.error(f"TCPClient ({self.client_id}): Error processing message: {e_msg_proc} for data: {message_str}", exc_info=True)

            except ConnectionResetError:
                logger.warning(f"TCPClient ({self.client_id}): Connection reset by peer.")
                await self._handle_disconnection()
                break
            except asyncio.IncompleteReadError:
                logger.warning(f"TCPClient ({self.client_id}): Incomplete read, connection likely closed.")
                await self._handle_disconnection()
                break
            except Exception as e_loop:
                logger.error(f"TCPClient ({self.client_id}): Error in receive loop: {e_loop}", exc_info=True)
                await self._handle_disconnection()
                break
        logger.info(f"TCPClient ({self.client_id}): Receive loop ended.")

    async def _send_message_internal(self, message: BaseMessage) -> bool:
        if not self.is_connected or not self.writer or self.writer.is_closing():
            logger.warning(f"TCPClient ({self.client_id}): Not connected or writer closed, cannot send message type {message.message_type}.")
            return False
        try:
            json_message = message.model_dump_json()
            logger.debug(f"TCPClient ({self.client_id}): Sending: {json_message}")
            self.writer.write(json_message.encode("utf-8") + b"\n")
            await self.writer.drain()
            return True
        except ConnectionResetError:
            logger.warning(f"TCPClient ({self.client_id}): Connection reset while sending message type {message.message_type}.")
            await self._handle_disconnection()
        except Exception as e:
            logger.error(f"TCPClient ({self.client_id}): Error sending message type {message.message_type}: {e}", exc_info=True)
            await self._handle_disconnection()
        return False

    async def send_heartbeat(self, hb_payload_override: Optional[HeartbeatPayload] = None) -> bool:
        payload = hb_payload_override if hb_payload_override else HeartbeatPayload(
            local_server_id=self.client_id,
            status="ok",
            model_name=settings.vllm.model_name_or_path,
            # TODO: Add actual vllm_health_status and active_tasks_count here
        )
        message = BaseMessage(message_type="heartbeat", payload=payload.model_dump())
        return await self._send_message_internal(message)

    async def request_cloud_refinement(self, request_data: LocalRequestCloudRefinementPayload, timeout: Optional[float] = None) -> Optional[CloudRefinementResponseToLocalPayload]:
        if not self.is_connected:
            logger.error(f"TCPClient ({self.client_id}): Cannot request cloud refinement, not connected.")
            raise TCPClientConnectionError("Not connected to remote server for refinement")

        task_id = str(uuid.uuid4())
        message = BaseMessage(task_id=task_id, message_type="local_request_cloud_refinement", payload=request_data.model_dump())
        
        future = asyncio.get_event_loop().create_future()
        self._pending_requests[task_id] = future
        
        if not await self._send_message_internal(message):
            self._pending_requests.pop(task_id, None)
            raise TCPClientConnectionError("Failed to send cloud refinement request")
        
        try:
            effective_timeout = timeout if timeout is not None else settings.remote_server.cloud_request_timeout_seconds
            logger.info(f"TCPClient ({self.client_id}): Waiting for cloud refinement response for task {task_id} with timeout {effective_timeout}s")
            response_payload_dict = await asyncio.wait_for(future, timeout=effective_timeout)
            return CloudRefinementResponseToLocalPayload(**response_payload_dict)
        except asyncio.TimeoutError as e_timeout:
            logger.warning(f"TCPClient ({self.client_id}): Timeout waiting for cloud refinement response for task {task_id}.")
            raise TCPClientTimeoutError(f"Timeout for task {task_id}") from e_timeout
        except Exception as e_resp:
            logger.error(f"TCPClient ({self.client_id}): Error processing cloud refinement response for task {task_id}: {e_resp}", exc_info=True)
            raise TCPClientError(f"Error processing response for task {task_id}: {e_resp}") from e_resp
        finally:
            self._pending_requests.pop(task_id, None)

    async def send_confident_result_notification(self, notification_data: LocalConfidentResultNotificationPayload) -> bool:
        message = BaseMessage(message_type="local_confident_result_notification", payload=notification_data.model_dump())
        return await self._send_message_internal(message)

    async def _handle_disconnection(self):
        async with self._connection_lock:
            if not self.is_connected: # Already handled or in process
                return
            logger.warning(f"TCPClient ({self.client_id}): Handling disconnection from {self.host}:{self.port}.")
            self.is_connected = False
            if self.writer:
                try:
                    if not self.writer.is_closing():
                        self.writer.close()
                    await self.writer.wait_closed()
                except Exception as e_writer_close:
                    logger.debug(f"TCPClient ({self.client_id}): Error closing writer: {e_writer_close}")
            self.writer = None
            self.reader = None
            
            for task_id, future in list(self._pending_requests.items()): # Iterate over a copy
                if not future.done():
                    future.set_exception(TCPClientConnectionError(f"Connection lost while waiting for response to task {task_id}"))
                self._pending_requests.pop(task_id, None)

            if self._receive_loop_task and not self._receive_loop_task.done():
                self._receive_loop_task.cancel()
                try: await self._receive_loop_task
                except asyncio.CancelledError: logger.debug(f"TCPClient ({self.client_id}): Receive loop task cancelled.")
                except Exception as e_task_cancel: logger.debug(f"TCPClient ({self.client_id}): Error awaiting cancelled receive loop: {e_task_cancel}")
            self._receive_loop_task = None

            if self.on_disconnect_callback:
                try: await self.on_disconnect_callback()
                except Exception as e_cb: logger.error(f"TCPClient ({self.client_id}): Error in on_disconnect_callback: {e_cb}", exc_info=True)

    async def maintain_connection_loop(self):
        logger.info(f"TCPClient ({self.client_id}): Maintain connection loop started.")
        reconnect_delay = settings.remote_server.tcp_client_reconnect_delay_seconds
        max_reconnect_delay = settings.remote_server.tcp_client_max_reconnect_delay_seconds

        while not self._shutdown_event.is_set():
            if not self.is_connected:
                logger.info(f"TCPClient ({self.client_id}): Attempting to connect/reconnect.")
                if await self.connect():
                    reconnect_delay = settings.remote_server.tcp_client_reconnect_delay_seconds # Reset delay on success
                else:
                    logger.info(f"TCPClient ({self.client_id}): Connection failed. Retrying in {reconnect_delay}s.")
                    try:
                        await asyncio.wait_for(self._shutdown_event.wait(), timeout=reconnect_delay)
                        if self._shutdown_event.is_set(): break # Exit if shutdown during sleep
                    except asyncio.TimeoutError:
                        pass # Expected timeout, continue to retry
                    reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)
            else: # Is connected
                # If connected, just wait for a short period or until shutdown is signaled.
                # The actual disconnection is handled by the receive loop or send errors.
                try:
                    await asyncio.wait_for(self._shutdown_event.wait(), timeout=1.0) 
                    if self._shutdown_event.is_set(): break
                except asyncio.TimeoutError:
                    pass # Normal check interval
        logger.info(f"TCPClient ({self.client_id}): Maintain connection loop ended due to shutdown.")

    async def start_heartbeat_loop(self, vllm_health_check_func: Optional[Callable[[], Awaitable[bool]]] = None, active_tasks_func: Optional[Callable[[], Awaitable[int]]] = None):
        if self._heartbeat_task and not self._heartbeat_task.done():
            logger.warning(f"TCPClient ({self.client_id}): Heartbeat loop already running.")
            return
        interval = settings.remote_server.heartbeat_interval_seconds
        logger.info(f"TCPClient ({self.client_id}): Starting heartbeat loop with interval {interval}s.")
        
        async def heartbeat_inner_loop():
            while not self._shutdown_event.is_set():
                try:
                    await asyncio.wait_for(self._shutdown_event.wait(), timeout=interval)
                    if self._shutdown_event.is_set(): break
                except asyncio.TimeoutError:
                    pass # Time for heartbeat

                if self.is_connected:
                    vllm_healthy = await vllm_health_check_func() if vllm_health_check_func else None
                    active_tasks = await active_tasks_func() if active_tasks_func else None
                    hb_payload = HeartbeatPayload(
                        local_server_id=self.client_id, 
                        status="ok", 
                        model_name=settings.vllm.model_name_or_path,
                        vllm_health_status=vllm_healthy,
                        active_tasks_count=active_tasks
                    )
                    logger.debug(f"TCPClient ({self.client_id}): Sending heartbeat.")
                    if not await self.send_heartbeat(hb_payload):
                        logger.warning(f"TCPClient ({self.client_id}): Failed to send heartbeat.")
                else:
                    logger.debug(f"TCPClient ({self.client_id}): Heartbeat: Not connected, skipping send.")
            logger.info(f"TCPClient ({self.client_id}): Heartbeat inner loop ended.")

        self._heartbeat_task = asyncio.create_task(heartbeat_inner_loop())

    async def close(self):
        logger.info(f"TCPClient ({self.client_id}): Initiating shutdown.")
        self._shutdown_event.set()
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try: await self._heartbeat_task
            except asyncio.CancelledError: logger.debug(f"TCPClient ({self.client_id}): Heartbeat task cancelled.")
        
        # The maintain_connection_loop will see _shutdown_event and exit.
        # The _receive_messages_loop will also see _shutdown_event and exit.
        await self._handle_disconnection() # Ensure final cleanup
        logger.info(f"TCPClient ({self.client_id}): Shutdown complete.")


