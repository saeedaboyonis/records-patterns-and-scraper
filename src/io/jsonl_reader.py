"""
Streaming JSONL file reader.

This module provides a memory-efficient reader for large JSONL files,
processing records one at a time without loading the entire file into memory.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Generator, Iterator, Union

from ..infra.logging import get_logger


logger = get_logger(__name__)


class JsonlReaderError(Exception):
    """Exception raised for JSONL reading errors."""
    pass


class JsonlReader:
    """
    Streaming reader for JSONL (JSON Lines) files.
    
    This class provides memory-efficient reading of large JSONL files
    by yielding one record at a time. It supports:
    - Streaming iteration over records
    - Error handling for malformed lines
    - Progress tracking and logging
    - Optional filtering during read
    
    Example:
        >>> reader = JsonlReader("data.jsonl")
        >>> for record in reader:
        ...     process(record)
    """
    
    def __init__(
        self,
        file_path: Union[str, Path],
        encoding: str = "utf-8",
        skip_errors: bool = True,
        log_interval: int = 10000,
    ):
        """
        Initialize the JSONL reader.
        
        Args:
            file_path: Path to the JSONL file
            encoding: File encoding (default: utf-8)
            skip_errors: If True, skip malformed lines; if False, raise errors
            log_interval: Log progress every N records
        """
        self.file_path = Path(file_path)
        self.encoding = encoding
        self.skip_errors = skip_errors
        self.log_interval = log_interval
        
        self._records_read = 0
        self._errors_encountered = 0
        self._validate_file()

    def _validate_file(self) -> None:
        """Validate that the file exists and is readable."""
        if not self.file_path.exists():
            raise JsonlReaderError(f"File not found: {self.file_path}")
        
        if not self.file_path.is_file():
            raise JsonlReaderError(f"Not a file: {self.file_path}")

    def __iter__(self) -> Iterator[dict[str, Any]]:
        """
        Iterate over records in the JSONL file.
        
        Yields:
            Dictionary representing each JSON record
        """
        return self.read()

    def read(self) -> Generator[dict[str, Any], None, None]:
        """
        Read and yield records from the JSONL file.
        
        This method streams records one at a time, allowing processing
        of files larger than available memory.
        
        Yields:
            Dictionary representing each JSON record
            
        Raises:
            JsonlReaderError: If skip_errors is False and a malformed line is found
        """
        self._records_read = 0
        self._errors_encountered = 0
        
        logger.info(f"Starting to read JSONL file: {self.file_path}")
        
        try:
            with open(self.file_path, "r", encoding=self.encoding) as f:
                for line_num, line in enumerate(f, start=1):
                    line = line.strip()
                    
                    # Skip empty lines
                    if not line:
                        continue
                    
                    try:
                        record = json.loads(line)
                        self._records_read += 1
                        
                        # Log progress
                        if self._records_read % self.log_interval == 0:
                            logger.info(f"Read {self._records_read:,} records...")
                        
                        yield record
                        
                    except json.JSONDecodeError as e:
                        self._errors_encountered += 1
                        error_msg = f"Line {line_num}: Invalid JSON - {e}"
                        
                        if self.skip_errors:
                            logger.warning(error_msg)
                        else:
                            raise JsonlReaderError(error_msg) from e
                            
        except IOError as e:
            raise JsonlReaderError(f"Error reading file: {e}") from e
        
        logger.info(
            f"Finished reading JSONL file. "
            f"Records: {self._records_read:,}, Errors: {self._errors_encountered:,}"
        )

    @property
    def records_read(self) -> int:
        """Get the number of records successfully read."""
        return self._records_read

    @property
    def errors_encountered(self) -> int:
        """Get the number of errors encountered."""
        return self._errors_encountered
