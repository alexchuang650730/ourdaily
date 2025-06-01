import logging
import sys
from ..core.config import settings

def setup_logging():
    """Configures basic logging for the application."""
    log_level = settings.log_level.upper()
    numeric_level = getattr(logging, log_level, None)
    if not isinstance(numeric_level, int):
        print(f"Warning: Invalid log level: {settings.log_level}. Defaulting to INFO.")
        numeric_level = logging.INFO

    # Basic configuration
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s - %(name)s - [%(levelname)s] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout  # Log to stdout, suitable for Docker
    )

    # You can customize further, e.g., set different levels for different loggers:
    # logging.getLogger("httpx").setLevel(logging.WARNING) # Quieten httpx logs
    # logging.getLogger("vllm").setLevel(logging.INFO) # If vllm client lib has its own logger

    logger = logging.getLogger(__name__)
    logger.info(f"Logging configured with level: {log_level}")

# Call setup_logging when this module is imported if you want it to apply globally immediately,
# or call it explicitly from main.py.
# For explicit control, it's better to call from main.py.

