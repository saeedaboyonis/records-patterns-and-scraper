"""
Domain models for property records and pattern analysis.

This module defines the core data structures using dataclasses and Pydantic
for validation. All models are immutable and support serialization to JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional
from enum import Enum


class StandardDocCategory(str, Enum):
    """Standard document categories for LLM classification."""
    SALE_DEED = "SALE_DEED"
    MORTGAGE = "MORTGAGE"
    DEED_OF_TRUST = "DEED_OF_TRUST"
    RELEASE = "RELEASE"
    LIEN = "LIEN"
    PLAT = "PLAT"
    EASEMENT = "EASEMENT"
    LEASE = "LEASE"
    MISC = "MISC"


@dataclass(frozen=True)
class Record:
    """
    Represents a single property record from any county.
    
    This is the canonical data structure used throughout the application.
    Fields may be None if data is missing from the source.
    
    Attributes:
        instrument_number: Unique identifier for the document
        parcel_number: Property parcel identifier
        county: County name (lowercase)
        state: State abbreviation (uppercase)
        book: Book reference number/identifier
        page: Page number within the book
        doc_type: Document type code
        doc_category: Document category grouping
        original_doc_type: Original document type from source
        book_type: Type of record book
        grantors: List of grantor names (uppercase)
        grantees: List of grantee names (uppercase)
        date: Document date in ISO 8601 format
        consideration: Monetary consideration amount
    """
    instrument_number: Optional[str] = None
    parcel_number: Optional[str] = None
    county: Optional[str] = None
    state: Optional[str] = None
    book: Optional[str] = None
    page: Optional[str] = None
    doc_type: Optional[str] = None
    doc_category: Optional[str] = None
    original_doc_type: Optional[str] = None
    book_type: Optional[str] = None
    grantors: tuple[str, ...] = field(default_factory=tuple)
    grantees: tuple[str, ...] = field(default_factory=tuple)
    date: Optional[str] = None
    consideration: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert record to dictionary for JSON serialization."""
        data = asdict(self)
        # Convert tuples to lists for JSON compatibility
        data["grantors"] = list(self.grantors) if self.grantors else []
        data["grantees"] = list(self.grantees) if self.grantees else []
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Record:
        """Create a Record from a dictionary."""
        # Convert lists to tuples for immutability
        grantors = tuple(data.get("grantors") or [])
        grantees = tuple(data.get("grantees") or [])
        
        return cls(
            instrument_number=data.get("instrument_number"),
            parcel_number=data.get("parcel_number"),
            county=data.get("county"),
            state=data.get("state"),
            book=data.get("book"),
            page=data.get("page"),
            doc_type=data.get("doc_type"),
            doc_category=data.get("doc_category"),
            original_doc_type=data.get("original_doc_type"),
            book_type=data.get("book_type"),
            grantors=grantors,
            grantees=grantees,
            date=data.get("date"),
            consideration=data.get("consideration"),
        )


@dataclass
class InstrumentPattern:
    """
    Represents a detected pattern in instrument numbers.
    
    Attributes:
        pattern: Human-readable pattern description
        regex: Regular expression matching the pattern
        example: Example value matching this pattern
        count: Number of occurrences
        percentage: Percentage of total records
        is_anomaly: Whether this pattern is considered anomalous
    """
    pattern: str
    regex: str
    example: str
    count: int
    percentage: float
    is_anomaly: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "pattern": self.pattern,
            "regex": self.regex,
            "example": self.example,
            "count": self.count,
            "percentage": round(self.percentage, 1),
        }


@dataclass
class BookPattern:
    """
    Represents a detected pattern in book or page values.
    
    Attributes:
        pattern: Human-readable pattern description
        regex: Regular expression matching the pattern
        example: Example value
        count: Number of occurrences
        percentage: Percentage of total
        is_numeric: Whether pattern is purely numeric
        has_letters: Whether pattern contains letters
        has_dashes: Whether pattern contains dashes
        min_value: Minimum numeric value (if numeric)
        max_value: Maximum numeric value (if numeric)
    """
    pattern: str
    regex: str
    example: str
    count: int
    percentage: float
    is_numeric: bool = False
    has_letters: bool = False
    has_dashes: bool = False
    min_value: Optional[int] = None
    max_value: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "pattern": self.pattern,
            "regex": self.regex,
            "example": self.example,
            "count": self.count,
            "percentage": round(self.percentage, 1),
        }


@dataclass
class DateRange:
    """
    Represents date range and anomalies for a county.
    
    Attributes:
        earliest: Earliest valid date found
        latest: Latest valid date found
        total_dates: Total number of date values
        valid_dates: Number of valid, parseable dates
        anomalies: List of anomaly date strings
    """
    earliest: Optional[str] = None
    latest: Optional[str] = None
    total_dates: int = 0
    valid_dates: int = 0
    anomalies: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "earliest": self.earliest,
            "latest": self.latest,
            "anomalies": self.anomalies,
        }


@dataclass
class CountyStats:
    """
    Aggregated statistics for a single county.
    
    Attributes:
        county: County name
        record_count: Total number of records
        instrument_patterns: Detected instrument number patterns
        book_patterns: Detected book patterns
        page_patterns: Detected page patterns
        date_range: Date range and anomalies
        doc_type_distribution: Simple dict mapping doc_type to count
        unique_doc_types: Count of unique document types
    """
    county: str
    record_count: int = 0
    instrument_patterns: list[InstrumentPattern] = field(default_factory=list)
    book_patterns: list[BookPattern] = field(default_factory=list)
    page_patterns: list[BookPattern] = field(default_factory=list)
    date_range: DateRange = field(default_factory=DateRange)
    doc_type_distribution: dict[str, int] = field(default_factory=dict)
    unique_doc_types: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "record_count": self.record_count,
            "instrument_patterns": [p.to_dict() for p in self.instrument_patterns],
            "book_patterns": [p.to_dict() for p in self.book_patterns],
            "date_range": self.date_range.to_dict(),
            "doc_type_distribution": self.doc_type_distribution,
            "unique_doc_types": self.unique_doc_types,
        }


@dataclass
class DocTypeMapping:
    """
    Mapping of an original document type to a standard category.
    
    Attributes:
        original_type: Original document type value
        standard_category: Assigned standard category
        confidence: Confidence score (0-1)
        frequency: Number of occurrences in dataset
        is_uncertain: Whether mapping is uncertain
        reasoning: LLM reasoning for the mapping
    """
    original_type: str
    standard_category: str
    confidence: float
    frequency: int
    is_uncertain: bool = False
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "original_type": self.original_type,
            "standard_category": self.standard_category,
            "confidence": round(self.confidence, 3),
            "frequency": self.frequency,
            "is_uncertain": self.is_uncertain,
            "reasoning": self.reasoning,
        }


@dataclass
class ClassificationResult:
    """
    Result from LLM document classification.
    
    Attributes:
        mappings: List of document type mappings
        total_types_processed: Total unique types processed
        total_records_covered: Total records covered by mappings
        uncertain_mappings: Count of uncertain mappings
        api_calls_made: Number of LLM API calls
        total_tokens_used: Total tokens consumed
        estimated_cost: Estimated API cost in USD
        dry_run: Whether this was a dry run (no actual API calls)
    """
    mappings: list[DocTypeMapping] = field(default_factory=list)
    total_types_processed: int = 0
    total_records_covered: int = 0
    uncertain_mappings: int = 0
    api_calls_made: int = 0
    total_tokens_used: int = 0
    estimated_cost: float = 0.0
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "summary": {
                "total_types_processed": self.total_types_processed,
                "total_records_covered": self.total_records_covered,
                "uncertain_mappings": self.uncertain_mappings,
                "api_calls_made": self.api_calls_made,
                "total_tokens_used": self.total_tokens_used,
                "estimated_cost_usd": round(self.estimated_cost, 4),
                "dry_run": self.dry_run,
            },
            "mappings": [m.to_dict() for m in self.mappings],
        }
