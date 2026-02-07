"""
County Pattern Analyzer - Task 1

This module processes JSONL records in streaming mode to analyze
patterns across counties including:
- Instrument number patterns
- Book/page patterns
- Date ranges and anomalies
- Document type distributions

Usage:
    python -m src.pattern_analyzer --input file.jsonl --output outputs/county_patterns.json
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .domain.models import (
    CountyStats,
    InstrumentPattern,
    BookPattern,
    DateRange,
)
from .domain.normalizers import DateNormalizer
from .io.jsonl_reader import JsonlReader
from .io.json_writer import JsonWriter
from .infra.logging import setup_logging, get_logger


logger = get_logger(__name__)


class PatternDetector:
    """
    Detects and categorizes patterns in string values.
    
    This class analyzes strings to identify common patterns
    and generate regular expressions that match them.
    """
    
    # Common instrument number patterns
    INSTRUMENT_PATTERNS = [
        (r"^\d{4}-\d{5,7}$", "YYYY-NNNNN(NN)", "Year-number format"),
        (r"^\d{4}-\d{3,4}$", "YYYY-NNN(N)", "Year-short number format"),
        (r"^bp-[a-z0-9-]+$", "bp-prefix", "Synthetic ID (bp prefix)"),
        (r"^BP-[A-Z0-9-]+$", "BP-PREFIX", "Synthetic ID (BP prefix uppercase)"),
        (r"^\d{10,}$", "NNNNNNNNNN+", "Long numeric only"),
        (r"^\d{6,9}$", "NNNNNN-NNNNNNNNN", "Medium numeric only"),
        (r"^\d{1,5}$", "N-NNNNN", "Short numeric only"),
        (r"^[A-Z]{1,3}-\d+$", "AAA-NNNN", "Letter prefix with number"),
        (r"^[A-Z]{2}\d{4}-\d+$", "AANNNN-NNNN", "State/county code format"),
        (r"^OR\d+$", "ORNNNNN", "OR prefix (Official Records)"),
        (r"^D\d+-\d+$", "DNNNN-NNNN", "D prefix format"),
    ]
    
    # Common book/page patterns
    BOOK_PAGE_PATTERNS = [
        (r"^\d+$", "numeric", "Numeric only"),
        (r"^[A-Z]+$", "alpha", "Letters only"),
        (r"^[A-Z]\d+$", "alpha-numeric", "Letter prefix with numbers"),
        (r"^\d+[A-Z]$", "numeric-alpha", "Numbers with letter suffix"),
        (r"^[A-Z]-\d+$", "alpha-dash-numeric", "Letter-dash-number"),
        (r"^\d+-\d+$", "numeric-range", "Number range"),
        (r"^[A-Z]{2,}\d+$", "prefix-numeric", "Multi-letter prefix"),
    ]

    @classmethod
    def detect_pattern(
        cls,
        value: str,
        pattern_list: list[tuple[str, str, str]]
    ) -> Optional[tuple[str, str, str]]:
        """
        Detect which pattern a value matches.
        
        Args:
            value: The value to analyze
            pattern_list: List of (regex, pattern_name, description) tuples
            
        Returns:
            Matched pattern tuple or None
        """
        for regex, pattern_name, description in pattern_list:
            if re.match(regex, value, re.IGNORECASE):
                return regex, pattern_name, description
        return None

    @classmethod
    def infer_pattern_from_value(cls, value: str) -> tuple[str, str]:
        """
        Infer a pattern from a single value.
        
        Args:
            value: The value to analyze
            
        Returns:
            Tuple of (pattern_description, regex)
        """
        # Build pattern by character classes
        pattern_parts = []
        regex_parts = []
        
        i = 0
        while i < len(value):
            char = value[i]
            
            if char.isdigit():
                # Count consecutive digits
                count = 1
                while i + count < len(value) and value[i + count].isdigit():
                    count += 1
                pattern_parts.append(f"N{{{count}}}")
                regex_parts.append(f"\\d{{{count}}}")
                i += count
            elif char.isalpha():
                # Count consecutive letters
                count = 1
                while i + count < len(value) and value[i + count].isalpha():
                    count += 1
                pattern_parts.append(f"A{{{count}}}")
                if value[i:i+count].isupper():
                    regex_parts.append(f"[A-Z]{{{count}}}")
                elif value[i:i+count].islower():
                    regex_parts.append(f"[a-z]{{{count}}}")
                else:
                    regex_parts.append(f"[A-Za-z]{{{count}}}")
                i += count
            else:
                # Special character
                pattern_parts.append(char)
                regex_parts.append(re.escape(char))
                i += 1
        
        return "".join(pattern_parts), "^" + "".join(regex_parts) + "$"


class CountyStatsAggregator:
    """
    Aggregates statistics for a single county during streaming.
    
    This class collects and maintains statistics as records are
    processed, without storing all records in memory.
    """
    
    def __init__(self, county: str):
        """
        Initialize the aggregator.
        
        Args:
            county: County name
        """
        self.county = county
        self.record_count = 0
        
        # Instrument patterns
        self.instrument_values: list[str] = []
        self.instrument_pattern_counts: Counter = Counter()
        self.instrument_pattern_examples: dict[tuple, str] = {}  # pattern_tuple -> example
        
        # Book patterns
        self.book_values: list[str] = []
        self.book_numeric_values: list[int] = []
        
        # Page patterns
        self.page_values: list[str] = []
        self.page_numeric_values: list[int] = []
        
        # Date tracking
        self.dates: list[datetime] = []
        self.date_anomalies: list[str] = []
        
        # Doc type tracking - simple count dict
        self.doc_type_counts: Counter = Counter()
        
        # Sampling limits to control memory
        self.MAX_SAMPLES = 1000
        self.date_normalizer = DateNormalizer()

    def add_record(self, record: dict[str, Any]) -> None:
        """
        Add a record to the aggregation.
        
        Args:
            record: Raw record dictionary
        """
        self.record_count += 1
        
        # Process instrument number (skip empty/missing values)
        inst_num = record.get("instrument_number")
        if inst_num:
            inst_str = str(inst_num).strip()
            # Only process non-empty instrument numbers
            if inst_str:
                if len(self.instrument_values) < self.MAX_SAMPLES:
                    self.instrument_values.append(inst_str)
                
                # Detect and count pattern
                pattern = PatternDetector.detect_pattern(
                    inst_str,
                    PatternDetector.INSTRUMENT_PATTERNS
                )
                if pattern:
                    self.instrument_pattern_counts[pattern] += 1
                    # Store example for this pattern if not already stored
                    if pattern not in self.instrument_pattern_examples:
                        self.instrument_pattern_examples[pattern] = inst_str
                else:
                    # Infer pattern
                    inferred = PatternDetector.infer_pattern_from_value(inst_str)
                    key = (inferred[1], inferred[0], "Inferred")
                    self.instrument_pattern_counts[key] += 1
                    # Store example for inferred pattern if not already stored
                    if key not in self.instrument_pattern_examples:
                        self.instrument_pattern_examples[key] = inst_str
        
        # Process book
        book = record.get("book")
        if book:
            book_str = str(book)
            if len(self.book_values) < self.MAX_SAMPLES:
                self.book_values.append(book_str)
            if book_str.isdigit():
                self.book_numeric_values.append(int(book_str))
        
        # Process page
        page = record.get("page")
        if page:
            page_str = str(page)
            if len(self.page_values) < self.MAX_SAMPLES:
                self.page_values.append(page_str)
            if page_str.isdigit():
                self.page_numeric_values.append(int(page_str))
        
        # Process date
        date_str = record.get("date")
        if date_str:
            parsed = self.date_normalizer.parse_for_comparison(date_str)
            if parsed:
                # Check for anomalies - future dates or very old dates
                now = datetime.now(timezone.utc)
                if parsed > now:
                    # Future date - anomaly
                    self.date_anomalies.append(str(date_str))
                elif parsed.year < 1800:
                    # Very old date - anomaly
                    self.date_anomalies.append(str(date_str))
                else:
                    # Valid date - include in range calculation
                    self.dates.append(parsed)
            else:
                self.date_anomalies.append(str(date_str)[:50])
        
        # Process doc types - simple count
        doc_type = record.get("doc_type")
        if doc_type:
            self.doc_type_counts[doc_type] += 1

    def build_stats(self) -> CountyStats:
        """
        Build final statistics from aggregated data.
        
        Returns:
            CountyStats object with all computed statistics
        """
        stats = CountyStats(county=self.county)
        stats.record_count = self.record_count
        
        # Build instrument patterns
        stats.instrument_patterns = self._build_instrument_patterns()
        
        # Build book patterns
        stats.book_patterns = self._build_value_patterns(
            self.book_values,
            self.book_numeric_values,
            "book"
        )
        
        # Build page patterns
        stats.page_patterns = self._build_value_patterns(
            self.page_values,
            self.page_numeric_values,
            "page"
        )
        
        # Build date range
        stats.date_range = self._build_date_range()
        
        # Build doc type distribution - simple dict of doc_type -> count
        stats.doc_type_distribution = dict(self.doc_type_counts)
        stats.unique_doc_types = len(self.doc_type_counts)
        
        return stats

    def _build_instrument_patterns(self) -> list[InstrumentPattern]:
        """Build instrument number pattern analysis."""
        patterns = []
        
        # Calculate total non-empty instrument numbers for percentage
        total_instruments = sum(self.instrument_pattern_counts.values())
        
        # Group by pattern
        for pattern_key, count in self.instrument_pattern_counts.most_common():
            regex, pattern_name, description = pattern_key
            
            # Get the stored example (guaranteed non-empty since we stored on first match)
            example = self.instrument_pattern_examples.get(pattern_key, "")
            
            # Skip patterns with no example (shouldn't happen, but safety check)
            if not example:
                continue
            
            # Calculate percentage based on total non-empty instrument numbers
            percentage = (count / total_instruments * 100) if total_instruments > 0 else 0
            
            # Mark as anomaly if very rare
            is_anomaly = percentage < 1.0 and count < 10
            
            # Convert anchored regex to pattern template (strip ^ and $)
            pattern_template = regex
            if pattern_template.startswith("^"):
                pattern_template = pattern_template[1:]
            if pattern_template.endswith("$"):
                pattern_template = pattern_template[:-1]
            
            patterns.append(InstrumentPattern(
                pattern=pattern_template,
                regex=regex,
                example=example,
                count=count,
                percentage=percentage,
                is_anomaly=is_anomaly,
            ))
        
        return patterns

    def _build_value_patterns(
        self,
        values: list[str],
        numeric_values: list[int],
        field_name: str
    ) -> list[BookPattern]:
        """Build book or page pattern analysis."""
        patterns = []
        pattern_counts: Counter = Counter()
        pattern_examples: dict[str, str] = {}
        
        # Analyze patterns
        for value in values:
            pattern = PatternDetector.detect_pattern(
                value,
                PatternDetector.BOOK_PAGE_PATTERNS
            )
            if pattern:
                pattern_counts[pattern] += 1
                if pattern not in pattern_examples:
                    pattern_examples[pattern] = value
            else:
                # Infer pattern
                inferred = PatternDetector.infer_pattern_from_value(value)
                key = (inferred[1], inferred[0], "Inferred")
                pattern_counts[key] += 1
                if key not in pattern_examples:
                    pattern_examples[key] = value
        
        total = len(values) if values else 1
        
        for (regex, pattern_name, description), count in pattern_counts.most_common():
            is_numeric = pattern_name == "numeric"
            has_letters = bool(re.search(r"[A-Za-z]", pattern_name))
            has_dashes = "-" in regex
            
            min_val = min(numeric_values) if numeric_values and is_numeric else None
            max_val = max(numeric_values) if numeric_values and is_numeric else None
            
            patterns.append(BookPattern(
                pattern=pattern_name,
                regex=regex,
                example=pattern_examples.get((regex, pattern_name, description), ""),
                count=count,
                percentage=(count / total * 100),
                is_numeric=is_numeric,
                has_letters=has_letters,
                has_dashes=has_dashes,
                min_value=min_val,
                max_value=max_val,
            ))
        
        return patterns

    def _build_date_range(self) -> DateRange:
        """Build date range analysis."""
        date_range = DateRange()
        date_range.total_dates = len(self.dates) + len(self.date_anomalies)
        date_range.valid_dates = len(self.dates)
        
        if self.dates:
            # Sort dates
            sorted_dates = sorted(self.dates)
            # Format as YYYY-MM-DD only
            date_range.earliest = sorted_dates[0].strftime("%Y-%m-%d")
            date_range.latest = sorted_dates[-1].strftime("%Y-%m-%d")
        
        # Simple list of anomalies
        date_range.anomalies = self.date_anomalies[:10]  # Limit to 10 examples
        
        return date_range


class PatternAnalyzer:
    """
    Main pattern analyzer that orchestrates the analysis.
    
    This class coordinates streaming through records, aggregating
    statistics per county, and generating the final output.
    """
    
    def __init__(
        self,
        input_path: str,
        output_path: str,
    ):
        """
        Initialize the pattern analyzer.
        
        Args:
            input_path: Path to input JSONL file
            output_path: Path for output JSON file
        """
        self.input_path = Path(input_path)
        self.output_path = Path(output_path)
        
        self.aggregators: dict[str, CountyStatsAggregator] = {}

    def analyze(self) -> dict[str, Any]:
        """
        Run the pattern analysis.
        
        Returns:
            Dictionary of county statistics
        """
        logger.info(f"Starting pattern analysis on: {self.input_path}")
        
        # Create reader
        reader = JsonlReader(
            file_path=self.input_path,
            skip_errors=True,
            log_interval=10000,
        )
        
        # Stream through records
        for record in reader:
            county = record.get("county", "unknown")
            if county:
                county = county.lower().strip()
            else:
                county = "unknown"
            
            # Get or create aggregator for this county
            if county not in self.aggregators:
                self.aggregators[county] = CountyStatsAggregator(county)
            
            self.aggregators[county].add_record(record)
        
        # Build final statistics
        results = {}
        for county, aggregator in sorted(self.aggregators.items()):
            logger.info(f"Building statistics for county: {county}")
            stats = aggregator.build_stats()
            results[county] = stats.to_dict()
        
        # Write output
        logger.info(f"Writing results to: {self.output_path}")
        writer = JsonWriter(self.output_path)
        writer.write(results)
        
        # Log summary
        total_records = sum(a.record_count for a in self.aggregators.values())
        logger.info(
            f"Analysis complete. "
            f"Processed {total_records:,} records across {len(self.aggregators)} counties"
        )
        
        return results


def main():
    """Main entry point for the pattern analyzer CLI."""
    parser = argparse.ArgumentParser(
        description="Analyze patterns in county property records",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.pattern_analyzer --input nc_records.jsonl --output outputs/county_patterns.json
  python -m src.pattern_analyzer -i data.jsonl -o results.json --log-level DEBUG
        """
    )
    
    parser.add_argument(
        "--input", "-i",
        required=True,
        help="Path to input JSONL file"
    )
    
    parser.add_argument(
        "--output", "-o",
        default="outputs/county_patterns.json",
        help="Path for output JSON file (default: outputs/county_patterns.json)"
    )
    
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level (default: INFO)"
    )
    
    parser.add_argument(
        "--log-file",
        help="Optional log file path"
    )
    
    args = parser.parse_args()
    
    # Setup logging
    import logging
    log_level = getattr(logging, args.log_level)
    log_file = Path(args.log_file) if args.log_file else None
    setup_logging(level=log_level, log_file=log_file)
    
    # Validate input file
    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        sys.exit(1)
    
    # Run analysis
    try:
        analyzer = PatternAnalyzer(
            input_path=str(input_path),
            output_path=args.output,
        )
        results = analyzer.analyze()
        
        # Print summary
        print(f"\n{'='*60}")
        print("ANALYSIS SUMMARY")
        print(f"{'='*60}")
        for county, stats in sorted(results.items()):
            print(f"\n{county.upper()}:")
            print(f"  Records: {stats['record_count']:,}")
            print(f"  Unique doc types: {stats['unique_doc_types']}")
            print(f"  Instrument patterns: {len(stats['instrument_patterns'])}")
            if stats['date_range']['earliest']:
                print(f"  Date range: {stats['date_range']['earliest'][:10]} to {stats['date_range']['latest'][:10]}")
        
        print(f"\n{'='*60}")
        print(f"Results written to: {args.output}")
        
    except Exception as e:
        logger.error(f"Analysis failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
