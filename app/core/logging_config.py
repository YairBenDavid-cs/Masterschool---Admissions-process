"""
Centralized logging configuration and logger factory for the application.
"""

# Standard Library
import logging
import sys


# =============================================================================
# SETUP
# =============================================================================

def setup_logging() -> None:
    """
    Configures the global logging settings for the application.

    Sets the log level to INFO and defines a standard format that includes
    timestamps, logger names, and severity levels. All logs are directed
    to sys.stdout for container compatibility.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )


# =============================================================================
# FACTORY
# =============================================================================

def get_logger(name: str) -> logging.Logger:
    """
    Creates and returns a named logger instance.

    Args:
        name (str): The name of the module (usually __name__).

    Returns:
        logging.Logger: A configured logger instance for the module.
    """
    return logging.getLogger(name)
