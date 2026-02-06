"""
Structured logging configuration.

This module provides a centralized logging setup with:
- Structured log output (JSON format option)
- Configurable log levels
- File and console handlers
- Context-aware logging
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


# Global log format
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Default log level
DEFAULT_LOG_LEVEL = logging.INFO


class StructuredFormatter(logging.Formatter):
    """
    Custom formatter that outputs structured log messages.
    
    Supports both human-readable and JSON formats.
    """
    
    def __init__(
        self,
        fmt: Optional[str] = None,
        datefmt: Optional[str] = None,
        json_format: bool = False,
    ):
        """
        Initialize the formatter.
        
        Args:
            fmt: Log format string
            datefmt: Date format string
            json_format: If True, output JSON-formatted logs
        """
        super().__init__(fmt or LOG_FORMAT, datefmt or LOG_DATE_FORMAT)
        self.json_format = json_format

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record."""
        if self.json_format:
            return self._format_json(record)
        return super().format(record)

    def _format_json(self, record: logging.LogRecord) -> str:
        """Format the log record as JSON."""
        import json
        
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields
        if hasattr(record, "extra_data"):
            log_data["extra"] = record.extra_data
        
        return json.dumps(log_data)


class LoggerAdapter(logging.LoggerAdapter):
    """
    Logger adapter that adds context to log messages.
    
    Allows adding extra context to all log messages from a logger.
    """
    
    def process(
        self,
        msg: str,
        kwargs: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        """Process the log message with context."""
        extra = kwargs.get("extra", {})
        extra.update(self.extra)
        kwargs["extra"] = extra
        return msg, kwargs


_loggers: dict[str, logging.Logger] = {}
_is_configured = False


def setup_logging(
    level: int = DEFAULT_LOG_LEVEL,
    log_file: Optional[Path] = None,
    json_format: bool = False,
) -> None:
    """
    Configure the logging system.
    
    Args:
        level: Log level (e.g., logging.INFO, logging.DEBUG)
        log_file: Optional path to log file
        json_format: If True, output JSON-formatted logs
    """
    global _is_configured
    
    # Create root logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Create formatter
    formatter = StructuredFormatter(json_format=json_format)
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # File handler (optional)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    _is_configured = True
    
    # Log startup
    logging.info(f"Logging configured at level {logging.getLevelName(level)}")


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance by name.
    
    Args:
        name: Logger name (typically __name__)
        
    Returns:
        Configured logger instance
    """
    global _is_configured
    
    # Auto-configure if not yet configured
    if not _is_configured:
        setup_logging()
    
    if name not in _loggers:
        _loggers[name] = logging.getLogger(name)
    
    return _loggers[name]


def get_context_logger(
    name: str,
    **context: Any
) -> LoggerAdapter:
    """
    Get a logger with context attached.
    
    Args:
        name: Logger name
        **context: Context key-value pairs to include in all log messages
        
    Returns:
        Logger adapter with context
    """
    logger = get_logger(name)
    return LoggerAdapter(logger, context)


class LogContext:
    """
    Context manager for temporary logging context.
    
    Example:
        >>> with LogContext(request_id="123"):
        ...     logger.info("Processing request")
    """
    
    def __init__(self, logger: logging.Logger, **context: Any):
        """
        Initialize the log context.
        
        Args:
            logger: Logger to add context to
            **context: Context key-value pairs
        """
        self.logger = logger
        self.context = context
        self._old_handlers: list[logging.Handler] = []

    def __enter__(self) -> logging.Logger:
        """Enter the context."""
        return LoggerAdapter(self.logger, self.context)

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit the context."""
        pass


def log_exception(
    logger: logging.Logger,
    message: str,
    exc: Exception,
    **extra: Any
) -> None:
    """
    Log an exception with full traceback.
    
    Args:
        logger: Logger instance
        message: Log message
        exc: Exception to log
        **extra: Additional context
    """
    logger.error(message, exc_info=exc, extra={"extra_data": extra})
