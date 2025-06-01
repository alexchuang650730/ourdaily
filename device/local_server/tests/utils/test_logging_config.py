import pytest
import logging
from unittest.mock import patch, MagicMock

from local_server.utils.logging_config import setup_logging
from local_server.core.config import AppSettings # Used by logging_config indirectly

# Fixture to reset logging state and AppSettings for each test
@pytest.fixture(autouse=True)
def reset_logging_and_settings():
    # Reset logging handlers to avoid interference between tests
    # From https://stackoverflow.com/questions/15795299/how-to-reset-the-logging-module-to-default-in-python
    # This is a bit aggressive but ensures a clean slate for handler checks.
    # More targeted handler removal might be better if specific handlers are added by tests.
    logging.shutdown()
    # Reload logging module to reset its state if necessary, though shutdown should be enough for handlers.
    # import importlib
    # importlib.reload(logging)

    # Ensure a fresh AppSettings instance for each test to avoid state leakage
    # This is important because setup_logging reads from settings.log_level
    with patch("local_server.utils.logging_config.settings", AppSettings()):
        yield
    
    # Clean up handlers again after test
    logging.shutdown()


def test_setup_logging_default_level(caplog):
    """Test that logging is configured with the default INFO level."""
    # Default AppSettings().log_level is INFO
    with patch("local_server.utils.logging_config.settings", AppSettings(log_level="INFO")):
        setup_logging()
    
    # Check that a logger (e.g., the root logger or the one in logging_config) logs INFO messages
    logger = logging.getLogger("local_server.utils.logging_config") # Get the logger used in setup_logging
    logger.info("This is an info message.")
    logger.debug("This is a debug message.") # Should not be captured

    assert "Logging configured with level: INFO" in caplog.text
    assert "This is an info message." in caplog.text
    assert "This is a debug message." not in caplog.text
    assert logging.getLogger().getEffectiveLevel() == logging.INFO

def test_setup_logging_debug_level(caplog):
    """Test that logging is configured with DEBUG level when specified."""
    with patch("local_server.utils.logging_config.settings", AppSettings(log_level="DEBUG")):
        setup_logging()

    logger = logging.getLogger("local_server.utils.logging_config")
    logger.info("Info for debug test.")
    logger.debug("Debug for debug test.")

    assert "Logging configured with level: DEBUG" in caplog.text
    assert "Info for debug test." in caplog.text
    assert "Debug for debug test." in caplog.text
    assert logging.getLogger().getEffectiveLevel() == logging.DEBUG

def test_setup_logging_warning_level(caplog):
    """Test that logging is configured with WARNING level."""
    with patch("local_server.utils.logging_config.settings", AppSettings(log_level="WARNING")):
        setup_logging()

    logger = logging.getLogger("local_server.utils.logging_config")
    logger.warning("Warning for warning test.")
    logger.info("Info for warning test.") # Should not be captured

    assert "Logging configured with level: WARNING" in caplog.text
    assert "Warning for warning test." in caplog.text
    assert "Info for warning test." not in caplog.text
    assert logging.getLogger().getEffectiveLevel() == logging.WARNING

def test_setup_logging_invalid_level(caplog):
    """Test that an invalid log level defaults to INFO with a warning."""
    with patch("local_server.utils.logging_config.settings", AppSettings(log_level="INVALID_LEVEL")):
        # Patch print within the logging_config module to capture the warning
        with patch("builtins.print") as mock_print:
            setup_logging()
    
    mock_print.assert_called_with("Warning: Invalid log level: INVALID_LEVEL. Defaulting to INFO.")
    
    logger = logging.getLogger("local_server.utils.logging_config")
    logger.info("Info after invalid level.")
    logger.debug("Debug after invalid level.") # Should not be captured

    assert "Logging configured with level: INFO" in caplog.text # The internal logger will still log this at INFO
    assert "Info after invalid level." in caplog.text
    assert "Debug after invalid level." not in caplog.text
    assert logging.getLogger().getEffectiveLevel() == logging.INFO

def test_logging_format(caplog):
    """Test the configured logging format."""
    with patch("local_server.utils.logging_config.settings", AppSettings(log_level="INFO")):
        setup_logging()
    
    logger = logging.getLogger("test_logger_format")
    logger.info("Test message for format check.")

    # Example log record: "2023-10-27 10:00:00 - test_logger_format - [INFO] - Test message for format check."
    # We can check for parts of the format.
    assert len(caplog.records) > 0
    # Find the specific log record
    test_record = None
    for record in caplog.records:
        if record.name == "test_logger_format" and record.message == "Test message for format check.":
            test_record = record
            break
    
    assert test_record is not None, "Test log record not found"
    assert test_record.levelname == "INFO"
    assert "- test_logger_format - [INFO] - Test message for format check." in test_record.getMessage() # Check the formatted part
    # Checking the timestamp format is tricky, so we check for its presence implicitly by the structure.
    # A more robust check might use regex on caplog.text or on the formatted record.

# To run these tests, you would typically use `pytest` in the terminal
# Ensure that the `local_server` directory is in PYTHONPATH or use pytest configurations for discovery.

