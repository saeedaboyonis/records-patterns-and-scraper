"""
Streaming JSONL file reader.

This module provides a memory-efficient reader for large JSONL files,
processing records one at a time without loading the entire file into memory.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Generator, Iterator, Optional, Union

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

    def read_filtered(
        self,
        filter_func: callable,
    ) -> Generator[dict[str, Any], None, None]:
        """
        Read and yield only records that match the filter function.
        
        Args:
            filter_func: Function that takes a record and returns True to include it
            
        Yields:
            Dictionary representing each matching JSON record
        """
        for record in self.read():
            if filter_func(record):
                yield record

    def read_sample(
        self,
        sample_size: int,
        strategy: str = "first"
    ) -> Generator[dict[str, Any], None, None]:
        """
        Read a sample of records.
        
        Args:
            sample_size: Maximum number of records to return
            strategy: Sampling strategy - "first", "random", or "stratified"
            
        Yields:
            Dictionary representing each sampled record
        """
        if strategy == "first":
            count = 0
            for record in self.read():
                if count >= sample_size:
                    break
                yield record
                count += 1
        else:
            # For other strategies, collect all records first
            # (not recommended for very large files)
            import random
            all_records = list(self.read())
            
            if strategy == "random":
                sample = random.sample(
                    all_records,
                    min(sample_size, len(all_records))
                )
                for record in sample:
                    yield record

    def count_records(self) -> int:
        """
        Count total records without loading them all into memory.
        
        Returns:
            Total number of valid records in the file
        """
        count = 0
        with open(self.file_path, "r", encoding=self.encoding) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        json.loads(line)
                        count += 1
                    except json.JSONDecodeError:
                        continue
        return count

    @property
    def records_read(self) -> int:
        """Get the number of records successfully read."""
        return self._records_read

    @property
    def errors_encountered(self) -> int:
        """Get the number of errors encountered."""
        return self._errors_encountered

    def get_stats(self) -> dict[str, Any]:
        """
        Get reading statistics.
        
        Returns:
            Dictionary with reading statistics
        """
        return {
            "file_path": str(self.file_path),
            "records_read": self._records_read,
            "errors_encountered": self._errors_encountered,
            "error_rate": (
                self._errors_encountered / 
                (self._records_read + self._errors_encountered)
                if (self._records_read + self._errors_encountered) > 0
                else 0.0
            ),
        }
