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
from typing import Optional


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
