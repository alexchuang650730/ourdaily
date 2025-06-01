import asyncio
import logging
import signal
import httpx

from local_server.core.config import settings
from local_server.utils.logging_config import setup_logging
from local_server.services.vllm_service import VLLMService
from local_server.services.confidence_service import ConfidenceService
from local_server.services.owl_agent_service import OwlAgentService
from local_server.services.task_orchestrator import TaskOrchestrator
from local_server.communication.tcp_client import TCPRemoteClient
from local_server.communication.tcp_server import start_tcp_server

logger = logging.getLogger(__name__)

# Global list to keep track of asyncio tasks to be cancelled on shutdown
background_tasks = set()

async def main():
    """Main function to initialize and run the local server components."""
    setup_logging()
    logger.info(f"Starting Local Server (ID: {settings.local_server_id}) with log level {settings.log_level}.")

    # Initialize HTTP client for services
    # Configure timeouts and limits for the HTTP client
    timeout_config = httpx.Timeout(settings.vllm.request_timeout, connect=10.0)
    limits_config = httpx.Limits(max_keepalive_connections=20, max_connections=100)
    async_http_client = httpx.AsyncClient(timeout=timeout_config, limits=limits_config)

    # Initialize services
    vllm_service = VLLMService(http_client=async_http_client)
    confidence_service = ConfidenceService()
    # Load keywords for confidence service during startup
    await confidence_service.load_keywords()
    
    owl_agent_service = OwlAgentService(vllm_service_instance=vllm_service)
    
    # Initialize TCP Remote Client (for communication with the cloud server)
    # The on_unsolicited_message_callback can be defined here if the orchestrator needs to handle them
    # For now, let's assume no specific unsolicited messages are expected beyond responses to requests.
    tcp_remote_client = TCPRemoteClient(
        host=settings.remote_server.host,
        port=settings.remote_server.command_port, # Assuming command port for general comms, or a dedicated one
        client_id=settings.local_server_id,
        # on_unsolicited_message_callback=handle_unsolicited_remote_message, # Define if needed
        # on_disconnect_callback=handle_remote_disconnect # Define if needed
    )

    task_orchestrator = TaskOrchestrator(
        vllm_service=vllm_service,
        confidence_service=confidence_service,
        owl_agent_service=owl_agent_service,
        tcp_remote_client=tcp_remote_client
    )

    # Start TCP client background tasks (maintain connection, heartbeat)
    maintain_conn_task = asyncio.create_task(tcp_remote_client.maintain_connection_loop())
    background_tasks.add(maintain_conn_task)
    
    # Pass health check and active tasks functions to heartbeat loop
    heartbeat_task = asyncio.create_task(tcp_remote_client.start_heartbeat_loop(
        vllm_health_check_func=vllm_service.check_health, 
        active_tasks_func=task_orchestrator.get_active_tasks_count
    ))
    background_tasks.add(heartbeat_task)

    # Start TCP Server (for receiving commands from the cloud server)
    # The message_handler for the TCP server will be a method from the TaskOrchestrator
    tcp_server_task = asyncio.create_task(start_tcp_server(
        host="0.0.0.0", # Listen on all interfaces within Docker
        port=settings.remote_server.command_port, # Port for incoming commands
        message_handler=task_orchestrator.process_incoming_tcp_message,
        server_id=settings.local_server_id
    ))
    background_tasks.add(tcp_server_task)

    logger.info("Local Server components initialized and started.")
    
    # Keep the main function alive until shutdown is triggered
    # The actual server tasks (tcp_server_task, maintain_conn_task, etc.) run in the background.
    # We wait for one of them to complete or an external shutdown signal.
    # For simplicity, we can just await the tcp_server_task as it's a primary foreground service.
    # Or, more robustly, wait for a shutdown event set by signal handlers.
    shutdown_event = asyncio.Event()
    
    # Add signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown(s, loop, shutdown_event)))
    
    logger.info("Local Server is running. Press Ctrl+C to stop.")
    await shutdown_event.wait() # Wait until shutdown is triggered

    # Cleanup tasks (already handled in shutdown function)
    logger.info("Closing HTTP client.")
    await async_http_client.aclose()
    logger.info("Local Server main function exiting.")

async def shutdown(sig: signal.Signals, loop: asyncio.AbstractEventLoop, shutdown_event_obj: asyncio.Event):
    logger.warning(f"Received exit signal {sig.name}...")
    
    # First, signal all loops that rely on shutdown_event to stop
    shutdown_event_obj.set()

    # Gracefully stop the TCP client (which cancels its internal tasks like heartbeat)
    # Assuming tcp_remote_client is accessible; if not, it needs to be passed or made global/class member
    # For this structure, we'd need to make it accessible or rely on task cancellation.
    # Let's find the TCPRemoteClient instance if it's part of a global context or passed around.
    # For now, we rely on cancelling its tasks directly.
    
    logger.info("Cancelling background tasks...")
    for task in list(background_tasks): # Iterate over a copy
        if task and not task.done():
            task.cancel()
    
    # Wait for tasks to actually cancel
    # This might take a moment if tasks have try/except asyncio.CancelledError clauses
    if background_tasks:
        await asyncio.gather(*[task for task in background_tasks if task], return_exceptions=True)
        logger.info("All background tasks cancelled or finished.")

    # Additional cleanup if necessary (e.g., closing other resources)
    # The HTTP client is closed in main after shutdown_event.wait() completes.

    # Stop the asyncio event loop
    # logger.info("Stopping event loop.")
    # loop.stop() # This is often not needed if main exits cleanly.

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Local Server stopped by KeyboardInterrupt.")
    except Exception as e_global:
        logger.critical(f"Local Server crashed with unhandled exception: {e_global}", exc_info=True)

