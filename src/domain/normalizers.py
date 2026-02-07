"""
Data normalizers for property records.

This module provides normalization utilities to standardize data
from various sources into a consistent format.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional
from dateutil import parser as date_parser


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
    Parses date values for comparison purposes.
    
    Handles various input formats and adds UTC timezone
    if not specified.
    """

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
