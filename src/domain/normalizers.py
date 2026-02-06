"""
Data normalizers for property records.

This module provides normalization utilities to standardize data
from various sources into a consistent format.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional
from dateutil import parser as date_parser
from dateutil.tz import tzutc

from .models import Record


class NameNormalizer:
    """
    Normalizes person and entity names.
    
    Applies consistent formatting rules:
    - Converts to uppercase
    - Removes extra whitespace
    - Standardizes suffixes
    """
    
    # Common name suffixes to standardize
    SUFFIXES = {
        r"\bJR\.?$": "JR",
        r"\bSR\.?$": "SR",
        r"\bII$": "II",
        r"\bIII$": "III",
        r"\bIV$": "IV",
        r"\bESQ\.?$": "ESQ",
        r"\bM\.?D\.?$": "MD",
        r"\bPHD\.?$": "PHD",
    }
    
    # Entity type abbreviations to standardize
    ENTITY_TYPES = {
        r"\bLLC\.?$": "LLC",
        r"\bINC\.?$": "INC",
        r"\bCORP\.?$": "CORP",
        r"\bL\.?P\.?$": "LP",
        r"\bL\.?L\.?P\.?$": "LLP",
        r"\bTRUST$": "TRUST",
        r"\bTRUSTEE$": "TRUSTEE",
    }

    @classmethod
    def normalize(cls, name: Optional[str]) -> Optional[str]:
        """
        Normalize a single name.
        
        Args:
            name: The name to normalize
            
        Returns:
            Normalized name in uppercase, or None if input is None/empty
        """
        if not name:
            return None
        
        # Convert to uppercase and strip whitespace
        normalized = name.upper().strip()
        
        # Remove extra internal whitespace
        normalized = re.sub(r"\s+", " ", normalized)
        
        # Standardize suffixes
        for pattern, replacement in cls.SUFFIXES.items():
            normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
        
        # Standardize entity types
        for pattern, replacement in cls.ENTITY_TYPES.items():
            normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
        
        return normalized if normalized else None

    @classmethod
    def normalize_list(cls, names: Optional[list[str]]) -> list[str]:
        """
        Normalize a list of names.
        
        Args:
            names: List of names to normalize
            
        Returns:
            List of normalized names (empty if input is None)
        """
        if not names:
            return []
        
        normalized = []
        for name in names:
            result = cls.normalize(name)
            if result:
                normalized.append(result)
        
        return normalized


class DateNormalizer:
    """
    Normalizes date values to ISO 8601 format with timezone.
    
    Handles various input formats and detects anomalies:
    - Future dates
    - Very old dates (before 1800)
    - Invalid date formats
    """
    
    # Reasonable date bounds for property records
    MIN_VALID_YEAR = 1800
    MAX_VALID_YEAR = datetime.now().year + 1  # Allow for near-future processing
    
    @classmethod
    def normalize(
        cls,
        date_value: Optional[str],
        default_timezone: timezone = timezone.utc
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Normalize a date value to ISO 8601 format.
        
        Args:
            date_value: The date string to normalize
            default_timezone: Timezone to use if not specified
            
        Returns:
            Tuple of (normalized_date, anomaly_type)
            anomaly_type is None if the date is valid
        """
        if not date_value:
            return None, None
        
        try:
            # Parse the date
            parsed = date_parser.parse(str(date_value))
            
            # Add timezone if missing
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=default_timezone)
            
            # Check for anomalies
            anomaly = cls._detect_anomaly(parsed)
            
            # Convert to ISO 8601 format
            normalized = parsed.isoformat()
            
            return normalized, anomaly
            
        except (ValueError, TypeError, OverflowError):
            return None, "invalid_format"

    @classmethod
    def _detect_anomaly(cls, date: datetime) -> Optional[str]:
        """
        Detect date anomalies.
        
        Args:
            date: Parsed datetime object
            
        Returns:
            Anomaly type string or None if no anomaly
        """
        now = datetime.now(timezone.utc)
        
        if date.year < cls.MIN_VALID_YEAR:
            return "extremely_old"
        
        if date > now:
            return "future_date"
        
        return None

    @classmethod
    def parse_for_comparison(cls, date_value: Optional[str]) -> Optional[datetime]:
        """
        Parse a date for comparison purposes.
        
        Args:
            date_value: The date string to parse
            
        Returns:
            Parsed datetime or None if invalid
        """
        if not date_value:
            return None
        
        try:
            parsed = date_parser.parse(str(date_value))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except (ValueError, TypeError, OverflowError):
            return None


class RecordNormalizer:
    """
    Normalizes property records to a consistent format.
    
    This class applies all field-specific normalization rules
    to convert raw data into a standardized Record object.
    """
    
    def __init__(
        self,
        default_state: str = "NC",
        default_timezone: timezone = timezone.utc
    ):
        """
        Initialize the normalizer.
        
        Args:
            default_state: Default state code if not specified
            default_timezone: Default timezone for dates
        """
        self.default_state = default_state
        self.default_timezone = default_timezone
        self.name_normalizer = NameNormalizer()
        self.date_normalizer = DateNormalizer()

    def normalize(self, data: dict[str, Any]) -> tuple[Record, list[str]]:
        """
        Normalize a raw record dictionary into a Record object.
        
        Args:
            data: Raw record data dictionary
            
        Returns:
            Tuple of (normalized Record, list of anomalies)
        """
        anomalies = []
        
        # Normalize date and collect anomaly
        normalized_date, date_anomaly = self.date_normalizer.normalize(
            data.get("date"),
            self.default_timezone
        )
        if date_anomaly:
            anomalies.append(f"date:{date_anomaly}")
        
        # Normalize names
        grantors = self.name_normalizer.normalize_list(data.get("grantors"))
        grantees = self.name_normalizer.normalize_list(data.get("grantees"))
        
        # Normalize county (lowercase)
        county = data.get("county")
        if county:
            county = county.lower().strip()
        
        # Normalize state (uppercase)
        state = data.get("state")
        if state:
            state = state.upper().strip()
        else:
            state = self.default_state
        
        # Normalize string fields
        instrument_number = self._normalize_string(data.get("instrument_number"))
        parcel_number = self._normalize_string(data.get("parcel_number"))
        book = self._normalize_string(data.get("book"))
        page = self._normalize_string(data.get("page"))
        doc_type = self._normalize_string(data.get("doc_type"))
        doc_category = self._normalize_string(data.get("doc_category"))
        original_doc_type = self._normalize_string(data.get("original_doc_type"))
        book_type = self._normalize_string(data.get("book_type"))
        
        # Normalize consideration
        consideration = self._normalize_consideration(data.get("consideration"))
        
        record = Record(
            instrument_number=instrument_number,
            parcel_number=parcel_number,
            county=county,
            state=state,
            book=book,
            page=page,
            doc_type=doc_type,
            doc_category=doc_category,
            original_doc_type=original_doc_type,
            book_type=book_type,
            grantors=tuple(grantors),
            grantees=tuple(grantees),
            date=normalized_date,
            consideration=consideration,
        )
        
        return record, anomalies

    @staticmethod
    def _normalize_string(value: Any) -> Optional[str]:
        """Normalize a string value."""
        if value is None:
            return None
        
        result = str(value).strip()
        return result if result else None

    @staticmethod
    def _normalize_consideration(value: Any) -> Optional[float]:
        """Normalize consideration value to float."""
        if value is None:
            return None
        
        try:
            # Handle string values with currency symbols
            if isinstance(value, str):
                # Remove currency symbols and commas
                cleaned = re.sub(r"[$,\s]", "", value)
                return float(cleaned) if cleaned else None
            
            return float(value)
        except (ValueError, TypeError):
            return None
