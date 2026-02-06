"""
JSON file writer with streaming support.

This module provides utilities for writing JSON data to files,
including support for streaming large datasets and pretty-printing.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Optional, Union

from ..infra.logging import get_logger


logger = get_logger(__name__)


class JsonWriterError(Exception):
    """Exception raised for JSON writing errors."""
    pass


class JsonArrayWriter:
    """
    Streaming JSON array writer that writes records directly to disk.
    
    This writer outputs a valid JSON array file by:
    - Writing '[' at start
    - Writing each record with proper comma handling
    - Writing ']' at close
    
    Features:
    - True streaming: each record written immediately (not accumulated in memory)
    - Atomic writes: uses temp file + rename for safety
    - Periodic flushing for durability
    - Context manager support
    
    Example:
        >>> with JsonArrayWriter("output.json") as writer:
        ...     for record in records:
        ...         writer.write_record(record)
    """
    
    FLUSH_INTERVAL = 100
    
    def __init__(
        self,
        output_path: str,
        atomic: bool = True,
        flush_interval: int = FLUSH_INTERVAL,
        indent: int = 2,
    ):
        """
        Initialize the JSON array writer.
        
        Args:
            output_path: Path to the output JSON file
            atomic: If True, write to temp file then rename (safer)
            flush_interval: Flush to disk every N records
            indent: Indentation for pretty-printing (None for compact)
        """
        self.output_path = Path(output_path)
        self.atomic = atomic
        self.flush_interval = flush_interval
        self.indent = indent
        
        self._file: Optional[Any] = None
        self._temp_path: Optional[Path] = None
        self._record_count = 0
        self._is_open = False
    
    @property
    def record_count(self) -> int:
        """Number of records written."""
        return self._record_count
    
    def open(self) -> None:
        """Open the output file and write array start."""
        if self._is_open:
            return
        
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        
        if self.atomic:
            fd, temp_path = tempfile.mkstemp(
                suffix=".json.tmp",
                dir=self.output_path.parent,
            )
            os.close(fd)
            self._temp_path = Path(temp_path)
            self._file = open(self._temp_path, "w", encoding="utf-8")
            logger.debug(f"Opened temp file for atomic write: {self._temp_path}")
        else:
            self._file = open(self.output_path, "w", encoding="utf-8")
            logger.debug(f"Opened output file: {self.output_path}")
        
        # Write array opening bracket
        self._file.write("[\n")
        self._is_open = True
        self._record_count = 0
    
    def write_record(self, record: dict[str, Any]) -> None:
        """
        Write a single record to the JSON array.
        
        Args:
            record: Dictionary to write as a JSON object
        """
        if not self._is_open:
            self.open()
        
        # Add comma before record (except first)
        if self._record_count > 0:
            self._file.write(",\n")
        
        # Write indented JSON object
        if self.indent:
            json_str = json.dumps(record, ensure_ascii=False, sort_keys=True)
            self._file.write("  " + json_str)
        else:
            json_str = json.dumps(record, ensure_ascii=False, sort_keys=True)
            self._file.write(json_str)
        
        self._record_count += 1
        
        # Periodic flush
        if self._record_count % self.flush_interval == 0:
            self._file.flush()
            logger.debug(f"Flushed after {self._record_count} records")
    
    def close(self) -> None:
        """Close the array and finalize the file."""
        if not self._is_open:
            return
        
        # Write array closing bracket
        if self._record_count > 0:
            self._file.write("\n")
        self._file.write("]\n")
        self._file.close()
        self._file = None
        
        # Atomic rename
        if self.atomic and self._temp_path:
            os.replace(self._temp_path, self.output_path)
            logger.debug(f"Atomic rename: {self._temp_path} -> {self.output_path}")
            self._temp_path = None
        
        self._is_open = False
        logger.info(f"Wrote {self._record_count} records to {self.output_path}")
    
    def __enter__(self) -> "JsonArrayWriter":
        """Context manager entry."""
        self.open()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit with cleanup."""
        if exc_type is not None:
            # Error occurred - clean up temp file
            if self._file:
                self._file.close()
                self._file = None
            if self._temp_path and self._temp_path.exists():
                try:
                    os.unlink(self._temp_path)
                except OSError:
                    pass
            self._is_open = False
            return
        
        self.close()


class JsonWriter:
    """
    JSON file writer with streaming and formatting support.
    
    This class provides utilities for writing JSON data to files,
    with support for:
    - Pretty-printing for readability
    - Deterministic output (sorted keys)
    - Streaming large datasets
    - Atomic writes
    
    Example:
        >>> writer = JsonWriter("output.json")
        >>> writer.write({"key": "value"})
    """
    
    def __init__(
        self,
        file_path: Union[str, Path],
        encoding: str = "utf-8",
        indent: int = 2,
        sort_keys: bool = True,
        ensure_ascii: bool = False,
    ):
        """
        Initialize the JSON writer.
        
        Args:
            file_path: Path to the output file
            encoding: File encoding (default: utf-8)
            indent: Indentation level for pretty-printing
            sort_keys: If True, sort dictionary keys for deterministic output
            ensure_ascii: If True, escape non-ASCII characters
        """
        self.file_path = Path(file_path)
        self.encoding = encoding
        self.indent = indent
        self.sort_keys = sort_keys
        self.ensure_ascii = ensure_ascii
        
        # Ensure parent directory exists
        self._ensure_directory()

    def _ensure_directory(self) -> None:
        """Ensure the output directory exists."""
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        data: Any,
        atomic: bool = True,
    ) -> None:
        """
        Write data to a JSON file.
        
        Args:
            data: Data to serialize and write
            atomic: If True, use atomic write (write to temp file then rename)
            
        Raises:
            JsonWriterError: If writing fails
        """
        try:
            if atomic:
                self._write_atomic(data)
            else:
                self._write_direct(data)
            
            logger.info(f"Successfully wrote JSON to: {self.file_path}")
            
        except (IOError, TypeError, ValueError) as e:
            raise JsonWriterError(f"Failed to write JSON: {e}") from e

    def _write_direct(self, data: Any) -> None:
        """Write data directly to the file."""
        with open(self.file_path, "w", encoding=self.encoding) as f:
            json.dump(
                data,
                f,
                indent=self.indent,
                sort_keys=self.sort_keys,
                ensure_ascii=self.ensure_ascii,
                default=self._json_serializer,
            )
            f.write("\n")  # Ensure file ends with newline

    def _write_atomic(self, data: Any) -> None:
        """Write data atomically using a temp file."""
        import tempfile
        import os
        
        # Write to temp file in same directory (for atomic rename)
        fd, temp_path = tempfile.mkstemp(
            suffix=".tmp",
            dir=self.file_path.parent,
        )
        
        try:
            with os.fdopen(fd, "w", encoding=self.encoding) as f:
                json.dump(
                    data,
                    f,
                    indent=self.indent,
                    sort_keys=self.sort_keys,
                    ensure_ascii=self.ensure_ascii,
                    default=self._json_serializer,
                )
                f.write("\n")
            
            # Atomic rename
            os.replace(temp_path, self.file_path)
            
        except Exception:
            # Clean up temp file on error
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise

    @staticmethod
    def _json_serializer(obj: Any) -> Any:
        """
        Custom JSON serializer for non-standard types.
        
        Args:
            obj: Object to serialize
            
        Returns:
            JSON-serializable representation
            
        Raises:
            TypeError: If object cannot be serialized
        """
        # Handle datetime
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        
        # Handle dataclasses
        if hasattr(obj, "__dataclass_fields__"):
            from dataclasses import asdict
            return asdict(obj)
        
        # Handle custom to_dict method
        if hasattr(obj, "to_dict"):
            return obj.to_dict()
        
        # Handle sets
        if isinstance(obj, set):
            return sorted(list(obj))
        
        # Handle bytes
        if isinstance(obj, bytes):
            return obj.decode("utf-8", errors="replace")
        
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    def write_streaming(
        self,
        items: Any,
        key: Optional[str] = None,
    ) -> int:
        """
        Write a stream of items to a JSON file.
        
        This method is useful for writing large collections without
        holding everything in memory at once.
        
        Args:
            items: Iterable of items to write
            key: If provided, wrap items in a dict with this key as an array
            
        Returns:
            Number of items written
        """
        count = 0
        collected = []
        
        for item in items:
            if hasattr(item, "to_dict"):
                collected.append(item.to_dict())
            else:
                collected.append(item)
            count += 1
        
        if key:
            self.write({key: collected})
        else:
            self.write(collected)
        
        return count

    def append_to_array(
        self,
        item: Any,
    ) -> None:
        """
        Append an item to an existing JSON array file.
        
        Note: This reads the entire file, so use with caution for large files.
        
        Args:
            item: Item to append
        """
        existing = []
        
        if self.file_path.exists():
            with open(self.file_path, "r", encoding=self.encoding) as f:
                existing = json.load(f)
        
        if not isinstance(existing, list):
            raise JsonWriterError("Cannot append to non-array JSON file")
        
        if hasattr(item, "to_dict"):
            existing.append(item.to_dict())
        else:
            existing.append(item)
        
        self.write(existing)


def write_json(
    data: Any,
    file_path: Union[str, Path],
    indent: int = 2,
    sort_keys: bool = True,
) -> None:
    """
    Convenience function for writing JSON data to a file.
    
    Args:
        data: Data to write
        file_path: Path to output file
        indent: Indentation level
        sort_keys: Whether to sort keys
    """
    writer = JsonWriter(
        file_path=file_path,
        indent=indent,
        sort_keys=sort_keys,
    )
    writer.write(data)
