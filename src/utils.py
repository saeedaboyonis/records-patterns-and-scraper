"""
Utility functions for the assessment solution.

This module provides common utility functions used across
the application.
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, TypeVar, Union


T = TypeVar("T")


def get_env_var(
    name: str,
    default: Optional[str] = None,
    required: bool = False,
) -> Optional[str]:
    """
    Get an environment variable with optional default and validation.
    
    Args:
        name: Environment variable name
        default: Default value if not set
        required: If True, raise error if not set
        
    Returns:
        Environment variable value or default
        
    Raises:
        ValueError: If required and not set
    """
    value = os.environ.get(name, default)
    
    if required and not value:
        raise ValueError(f"Required environment variable not set: {name}")
    
    return value


def ensure_directory(path: Union[str, Path]) -> Path:
    """
    Ensure a directory exists, creating it if necessary.
    
    Args:
        path: Directory path
        
    Returns:
        Path object for the directory
    """
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_filename(name: str, max_length: int = 255) -> str:
    """
    Convert a string to a safe filename.
    
    Args:
        name: Original name
        max_length: Maximum filename length
        
    Returns:
        Safe filename string
    """
    # Remove or replace unsafe characters
    safe = re.sub(r'[<>:"/\\|?*]', "_", name)
    safe = re.sub(r"\s+", "_", safe)
    safe = re.sub(r"_+", "_", safe)
    safe = safe.strip("._")
    
    # Truncate if necessary
    if len(safe) > max_length:
        safe = safe[:max_length]
    
    return safe


def generate_hash(data: Union[str, bytes], algorithm: str = "sha256") -> str:
    """
    Generate a hash of the given data.
    
    Args:
        data: Data to hash
        algorithm: Hash algorithm to use
        
    Returns:
        Hexadecimal hash string
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    
    hasher = hashlib.new(algorithm)
    hasher.update(data)
    return hasher.hexdigest()


def truncate_string(
    text: str,
    max_length: int,
    suffix: str = "...",
) -> str:
    """
    Truncate a string to a maximum length.
    
    Args:
        text: Text to truncate
        max_length: Maximum length including suffix
        suffix: Suffix to add when truncated
        
    Returns:
        Truncated string
    """
    if len(text) <= max_length:
        return text
    
    return text[:max_length - len(suffix)] + suffix


def parse_bool(value: Any) -> bool:
    """
    Parse a boolean value from various representations.
    
    Args:
        value: Value to parse
        
    Returns:
        Boolean value
    """
    if isinstance(value, bool):
        return value
    
    if isinstance(value, str):
        return value.lower() in ("true", "yes", "1", "on")
    
    return bool(value)


def coalesce(*args: Optional[T]) -> Optional[T]:
    """
    Return the first non-None argument.
    
    Args:
        *args: Values to check
        
    Returns:
        First non-None value, or None if all are None
    """
    for arg in args:
        if arg is not None:
            return arg
    return None


def chunk_list(lst: list[T], chunk_size: int) -> list[list[T]]:
    """
    Split a list into chunks of specified size.
    
    Args:
        lst: List to chunk
        chunk_size: Size of each chunk
        
    Returns:
        List of chunks
    """
    return [
        lst[i:i + chunk_size]
        for i in range(0, len(lst), chunk_size)
    ]


def flatten_dict(
    data: dict[str, Any],
    separator: str = ".",
    prefix: str = "",
) -> dict[str, Any]:
    """
    Flatten a nested dictionary.
    
    Args:
        data: Dictionary to flatten
        separator: Separator for nested keys
        prefix: Prefix for keys
        
    Returns:
        Flattened dictionary
    """
    result = {}
    
    for key, value in data.items():
        new_key = f"{prefix}{separator}{key}" if prefix else key
        
        if isinstance(value, dict):
            result.update(flatten_dict(value, separator, new_key))
        else:
            result[new_key] = value
    
    return result


def get_timestamp() -> str:
    """
    Get current UTC timestamp in ISO format.
    
    Returns:
        ISO 8601 timestamp string
    """
    return datetime.now(timezone.utc).isoformat()


def format_bytes(num_bytes: int) -> str:
    """
    Format bytes as human-readable string.
    
    Args:
        num_bytes: Number of bytes
        
    Returns:
        Human-readable string (e.g., "1.5 MB")
    """
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    
    return f"{num_bytes:.1f} PB"


def format_duration(seconds: float) -> str:
    """
    Format duration as human-readable string.
    
    Args:
        seconds: Duration in seconds
        
    Returns:
        Human-readable string (e.g., "2h 30m 15s")
    """
    if seconds < 60:
        return f"{seconds:.1f}s"
    
    minutes, seconds = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m {seconds}s"


def safe_get(
    data: dict[str, Any],
    *keys: str,
    default: Any = None,
) -> Any:
    """
    Safely get a nested value from a dictionary.
    
    Args:
        data: Dictionary to get value from
        *keys: Keys to traverse
        default: Default value if not found
        
    Returns:
        Value or default
    """
    current = data
    
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    
    return current


class Timer:
    """
    Simple timer for measuring execution time.
    
    Example:
        >>> with Timer() as t:
        ...     do_something()
        >>> print(f"Took {t.elapsed:.2f} seconds")
    """
    
    def __init__(self):
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None

    def __enter__(self) -> Timer:
        import time
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        import time
        self.end_time = time.perf_counter()

    @property
    def elapsed(self) -> float:
        """Get elapsed time in seconds."""
        import time
        end = self.end_time or time.perf_counter()
        start = self.start_time or end
        return end - start


class Singleton:
    """
    Singleton metaclass for creating singleton instances.
    
    Example:
        >>> class MyClass(metaclass=Singleton):
        ...     pass
    """
    
    _instances: dict[type, Any] = {}
    
    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]
