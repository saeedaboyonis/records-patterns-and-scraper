"""
Seminole County Property Records Scraper - Task 2

This module provides a robust scraper for the Seminole County Clerk's
public property records search system.

Target: https://recording.seminoleclerk.org/DuProcessWebInquiry/index.html

Features:
- Name-based search via CriteriaSearch API
- Adaptive sliding window search to bypass 2000-row server cap
- Deduplication using `gin` (global identifier)
- Rate limiting and respectful delays
- Retry logic with exponential backoff
- Record normalization to standard format (NC dataset compatible)

Important Notes:
- The CriteriaSearch API returns a maximum of 2000 rows per request.
- The UI shows "Pg 1 of 67" which is CLIENT-SIDE pagination over that 2000-row dataset.
- There is NO server-side pagination parameter in CriteriaSearch.
- To retrieve more than 2000 records, we use ADAPTIVE SLIDING WINDOW SEARCH:
  start from the end date, work backwards with a dynamic window that adjusts
  based on result density (shrinks when capped, expands when sparse).

Usage:
    python -m src.seminole_scraper --name "John Doe" --output outputs/seminole_test_results.json
    python -m src.seminole_scraper --name "Smith" --chunked --output outputs/smith_results.json
    python -m src.seminole_scraper --test --output outputs/seminole_test_results.json
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator, Optional
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .domain.models import Record
from .io.json_writer import JsonArrayWriter
from .infra.logging import setup_logging, get_logger


logger = get_logger(__name__)


# Timezone for Seminole County, FL
SEMINOLE_TZ = ZoneInfo("America/New_York")

# Server cap - CriteriaSearch returns max 2000 rows
SERVER_ROW_CAP = 2000

# Safety caps for sliding window search
MAX_API_REQUESTS = 500

# Sliding window parameters
DEFAULT_SPAN_DAYS = 160   # Initial window size
MIN_SPAN_DAYS = 1        # Minimum window size
MAX_SPAN_DAYS = 10 * 365      # Maximum window size (10 years)
LOW_THRESHOLD = 1000      # Below this row count, expand window
HIGH_THRESHOLD = SERVER_ROW_CAP  # At this row count, shrink window

# Required output schema fields (exactly 14, no more, no less)
REQUIRED_RECORD_FIELDS = frozenset({
    "instrument_number",
    "parcel_number",
    "county",
    "state",
    "book",
    "page",
    "doc_type",
    "doc_category",
    "original_doc_type",
    "book_type",
    "grantors",
    "grantees",
    "date",
    "consideration",
})


def validate_record(record: dict[str, Any]) -> bool:
    """
    Validate a single record against required schema.
    
    Per-record validation for streaming output. Does NOT raise exceptions -
    returns False and logs warning for invalid records.
    
    Requirements:
    - Must be a dict
    - Must have EXACTLY 14 keys matching REQUIRED_RECORD_FIELDS
    - grantors/grantees must be lists
    - county must be "seminole"
    - state must be "FL"
    
    Args:
        record: Single record dictionary to validate
        
    Returns:
        True if valid, False otherwise
    """
    if not isinstance(record, dict):
        logger.warning(f"Record must be a dict, got {type(record).__name__}")
        return False
    
    record_keys = set(record.keys())
    
    # Check for exactly 14 keys
    if len(record_keys) != 14:
        logger.warning(
            f"Record has {len(record_keys)} keys, expected 14. "
            f"inst_num={record.get('instrument_number')}"
        )
        return False
    
    # Check for missing fields
    missing = REQUIRED_RECORD_FIELDS - record_keys
    if missing:
        logger.warning(f"Record missing fields: {missing}")
        return False
    
    # Check for extra fields
    extra = record_keys - REQUIRED_RECORD_FIELDS
    if extra:
        logger.warning(f"Record has extra fields: {extra}")
        return False
    
    # Validate types
    if not isinstance(record.get("grantors"), list):
        logger.warning(f"grantors must be a list, got {type(record.get('grantors'))}")
        return False
    if not isinstance(record.get("grantees"), list):
        logger.warning(f"grantees must be a list, got {type(record.get('grantees'))}")
        return False
    if record.get("county") != "seminole":
        logger.warning(f"county must be 'seminole', got '{record.get('county')}'")
        return False
    if record.get("state") != "FL":
        logger.warning(f"state must be 'FL', got '{record.get('state')}'")
        return False
    
    return True


class SeminoleScraperError(Exception):
    """Exception raised for scraper errors."""
    pass


class SeminoleScraper:
    """
    Scraper for Seminole County Clerk's property records.
    
    This class provides methods to search and extract property records
    from the Seminole County Clerk's public inquiry system using the
    CriteriaSearch API endpoint.
    
    Features:
    - Name-based search via JSON API
    - Session cookie warmup
    - Adaptive sliding window search to bypass 2000-row cap
    - Deduplication using `gin` (global identifier)
    - Rate limiting with jitter
    - Automatic retry with exponential backoff
    - Record normalization to NC dataset schema
    
    Important:
        The CriteriaSearch API returns at most 2000 rows. The UI's "Pg 1 of 67"
        is client-side pagination over that capped dataset. To get more results,
        enable chunked mode which uses adaptive sliding window search.
    
    Example:
        >>> scraper = SeminoleScraper()
        >>> records = scraper.search_by_name("Smith", chunked=True)
        >>> print(f"Found {len(records)} unique records")
    """
    
    BASE_URL = "https://recording.seminoleclerk.org/DuProcessWebInquiry"
    SEARCH_ENDPOINT = f"{BASE_URL}/Home/CriteriaSearch"
    INDEX_URL = f"{BASE_URL}/index.html"
    
    # Constants
    COUNTY = "seminole"
    STATE = "FL"
    
    def __init__(
        self,
        requests_per_second: float = 0.5,
        min_delay: float = 2.0,
        max_delay: float = 5.0,
        max_retries: int = 3,
        timeout: float = 180.0,
        chunked_min_delay: float = 1.0,
        chunked_max_delay: float = 2.0,
    ):
        """
        Initialize the Seminole County scraper.
        
        Args:
            requests_per_second: Rate limit for requests
            min_delay: Minimum delay between requests in seconds
            max_delay: Maximum delay between requests (for jitter)
            max_retries: Maximum retry attempts for failed requests
            timeout: Request timeout in seconds
            chunked_min_delay: Min delay for chunked mode (faster)
            chunked_max_delay: Max delay for chunked mode (faster)
        """
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.chunked_min_delay = chunked_min_delay
        self.chunked_max_delay = chunked_max_delay
        self.timeout = timeout
        self.max_retries = max_retries
        
        # Setup session with retry strategy
        self.session = requests.Session()
        
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=1.0,  # Exponential backoff: 1s, 2s, 4s
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        
        # Set default headers to mimic browser
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        })
        
        # Session initialized flag
        self._session_warmed = False
        
        # Performance tracking
        self._request_count = 0
        self._start_time: Optional[float] = None
        
        # Chunked mode flag for delay adjustment
        self._chunked_mode = False

    def _warmup_session(self) -> None:
        """
        Warm up session by fetching index.html to get cookies.
        
        This ensures the session has valid cookies before making
        API requests.
        """
        if self._session_warmed:
            return
        
        logger.info("Warming up session (fetching index.html for cookies)...")
        
        try:
            response = self.session.get(
                self.INDEX_URL,
                timeout=self.timeout,
            )
            response.raise_for_status()
            self._session_warmed = True
            logger.debug(f"Session warmed up. Cookies: {list(self.session.cookies.keys())}")
        except requests.RequestException as e:
            logger.warning(f"Session warmup failed: {e}. Proceeding anyway...")
            self._session_warmed = True  # Don't retry warmup

    def _delay_with_jitter(self) -> None:
        """Apply a random delay with jitter. Uses faster delays in chunked mode."""
        if self._chunked_mode:
            delay = random.uniform(self.chunked_min_delay, self.chunked_max_delay)
        else:
            delay = random.uniform(self.min_delay, self.max_delay)
        time.sleep(delay)

    def search_by_name(
        self,
        name: str,
        max_results: Optional[int] = None,
        date_start: str = "1/1/2020",
        date_end: Optional[str] = None,
        chunked: bool = True,
    ) -> list[Record]:
        """
        Search for records by name.
        
        This is the main public API method. It searches for property
        records matching the given name and returns normalized records.
        
        Args:
            name: Name to search for (e.g., "Smith John" or "John Smith")
            max_results: Maximum number of results to return (None for all)
            date_start: Start date for search range (default: 1/1/1913)
            date_end: End date for search range (default: today)
            chunked: If True, use adaptive sliding window to bypass 2000-row cap
            
        Returns:
            List of Record objects matching the search
            
        Raises:
            SeminoleScraperError: If the search fails
        """
        self._start_time = time.time()
        self._request_count = 0
        self._chunked_mode = chunked
        
        logger.info(f"Starting search for name: '{name}' (chunked={chunked})")
        
        # Default end date to today
        if date_end is None:
            date_end = datetime.now(SEMINOLE_TZ).strftime("%m/%d/%Y")
        
        try:
            # Ensure session is warmed up
            self._warmup_session()
            
            # Parse date strings to datetime for sliding window
            start_dt = self._parse_date_str(date_start)
            end_dt = self._parse_date_str(date_end)
            
            # Execute search (single or chunked)
            if chunked:
                raw_results = self._chunked_search_fast(name, start_dt, end_dt, max_results)
            else:
                raw_results = self._search_range(name, start_dt, end_dt)
            
            # Deduplicate results
            unique_results = self._dedupe_results(raw_results)
            logger.info(f"After deduplication: {len(unique_results)} unique records (from {len(raw_results)} raw)")
            
            # Parse results into Records
            all_records = self._parse_result_rows(unique_results)
            
            # Apply max_results limit if specified
            if max_results and len(all_records) > max_results:
                all_records = all_records[:max_results]
            
            # Log performance metrics
            elapsed = time.time() - self._start_time
            records_per_min = (len(all_records) / elapsed * 60) if elapsed > 0 else 0
            
            logger.info(
                f"Search complete. Found {len(all_records)} records in {elapsed:.1f}s "
                f"({records_per_min:.1f} records/min, {self._request_count} API requests)"
            )
            
            return all_records
            
        except Exception as e:
            logger.error(f"Search failed: {e}")
            raise SeminoleScraperError(f"Search failed: {e}") from e

    def _parse_date_str(self, date_str: str) -> datetime:
        """Parse date string (M/D/YYYY or MM/DD/YYYY) to datetime."""
        for fmt in ["%m/%d/%Y", "%Y-%m-%d"]:
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                return dt.replace(tzinfo=SEMINOLE_TZ)
            except ValueError:
                continue
        raise ValueError(f"Cannot parse date: {date_str}")

    def _format_date_for_api(self, dt: datetime) -> str:
        """Format datetime for API criteria (M/D/YYYY)."""
        # Simple formatting that works cross-platform
        return f"{dt.month}/{dt.day}/{dt.year}"

    def _build_criteria(
        self,
        name: str,
        date_start: str,
        date_end: str,
    ) -> list[dict[str, Any]]:
        """
        Build the criteria array for the CriteriaSearch API.
        
        Args:
            name: Name to search for
            date_start: Start date (M/D/YYYY format)
            date_end: End date (M/D/YYYY or MM/DD/YYYY format)
            
        Returns:
            List containing one criteria dictionary
        """
        criteria = [{
            "direction": "",
            "name_direction": True,
            "full_name": name.strip().upper(),
            "file_date_start": date_start,
            "file_date_end": date_end,
            "inst_type": "",
            "inst_book_type_id": "",
            "location_id": "",
            "book_reel": "",
            "page_image": "",
            "greater_than_page": False,
            "inst_num": "",
            "description": "",
            "consideration_value_min": "",
            "consideration_value_max": "",
            "parcel_id": "",
            "legal_section": "",
            "legal_township": "",
            "legal_range": "",
            "legal_square": "",
            "subdivision_code": "",
            "block": "",
            "lot_from": "",
            "q_NWNW": False, "q_NWNE": False, "q_NWSE": False, "q_NWSW": False,
            "q_NENW": False, "q_NENE": False, "q_NESW": False, "q_NESE": False,
            "q_SWNW": False, "q_SWNE": False, "q_SWSW": False, "q_SWSE": False,
            "q_SENW": False, "q_SENE": False, "q_SESW": False, "q_SESE": False,
            "q_q_search_type": False,
            "address_street": "",
            "address_number": "",
            "address_parcel": "",
            "address_ppin": "",
            "patent_number": "",
        }]
        
        return criteria

    def _fetch_once(
        self,
        criteria: list[dict[str, Any]],
        log_request: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Make a single CriteriaSearch request and return results.
        
        This is the core fetch method - NO pagination loop.
        The server returns at most 2000 rows per request.
        
        Args:
            criteria: Criteria array for the API
            log_request: Whether to log this request (for reduced spam)
            
        Returns:
            List of result dictionaries from API (max 2000)
        """
        self._delay_with_jitter()
        self._request_count += 1
        
        # Log every 10 requests to reduce spam
        if log_request or self._request_count % 10 == 0:
            logger.debug(f"API request #{self._request_count}")
        
        try:
            # Make the API request
            response = self.session.get(
                self.SEARCH_ENDPOINT,
                params={
                    "criteria_array": json.dumps(criteria),
                },
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": self.INDEX_URL,
                },
                timeout=self.timeout,
            )
            
            response.raise_for_status()
            
        except requests.Timeout as e:
            logger.error(f"Request timed out: {e}")
            raise SeminoleScraperError(f"Request timed out: {e}") from e
        except requests.RequestException as e:
            logger.error(f"Request failed: {e}")
            raise SeminoleScraperError(f"Request failed: {e}") from e
        
        # Parse response
        return self._parse_response(response)

    def _search_range(
        self,
        name: str,
        start_dt: datetime,
        end_dt: datetime,
        log_request: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Search for a single date range (no windowing).
        
        Args:
            name: Name to search for
            start_dt: Start datetime
            end_dt: End datetime
            log_request: Whether to log this request
            
        Returns:
            List of result dictionaries (max 2000)
        """
        date_start = self._format_date_for_api(start_dt)
        date_end = self._format_date_for_api(end_dt)
        
        criteria = self._build_criteria(name, date_start, date_end)
        results = self._fetch_once(criteria, log_request=log_request)
        
        return results

    def _chunked_search_fast(
        self,
        name: str,
        start_dt: datetime,
        end_dt: datetime,
        max_results: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """
        Adaptive sliding window search to bypass 2000-row cap efficiently.
        
        Algorithm:
        1. Start from end_dt and work backwards towards start_dt
        2. Use a dynamic span_days that adjusts based on result counts:
           - If hit cap (2000 rows): shrink span_days by half
           - If sparse (<400 rows): expand span_days by 2x
           - If good (400-1999 rows): accept and move window back
        3. Handle single-day cap cases with warnings
        
        Args:
            name: Name to search for
            start_dt: Start datetime
            end_dt: End datetime
            max_results: Stop early if we reach this many unique results
            
        Returns:
            List of all result dictionaries across windows
        """
        all_results: list[dict[str, Any]] = []
        seen_gins: set[str] = set()
        unique_count = 0
        
        # Metrics tracking
        total_api_calls = 0
        rows_per_call: list[int] = []
        window_sizes: list[int] = []
        capped_single_days: list[str] = []
        
        # Sliding window state
        span_days = DEFAULT_SPAN_DAYS
        window_end = end_dt
        
        logger.info(
            f"Starting adaptive sliding window search: "
            f"{self._format_date_for_api(start_dt)} to {self._format_date_for_api(end_dt)} "
            f"(initial span: {span_days} days)"
        )
        
        while window_end >= start_dt:
            # Safety check
            if self._request_count >= MAX_API_REQUESTS:
                logger.warning(
                    f"⚠️  Reached max API requests ({MAX_API_REQUESTS}). "
                    f"Stopping with {unique_count} unique results."
                )
                break
            
            # Calculate window_start, clamped to start_dt
            window_start = window_end - timedelta(days=span_days - 1)
            if window_start < start_dt:
                window_start = start_dt
            
            # Fetch results for this window
            results = self._search_range(name, window_start, window_end, log_request=False)
            result_count = len(results)
            total_api_calls += 1
            rows_per_call.append(result_count)
            window_sizes.append(span_days)
            
            # Log progress
            logger.info(
                f"Window #{total_api_calls}: [{self._format_date_for_api(window_start)} - "
                f"{self._format_date_for_api(window_end)}] span={span_days}d → {result_count} rows"
            )
            
            # Decide action based on result count
            if result_count >= HIGH_THRESHOLD:
                # Hit cap - shrink window
                if span_days > MIN_SPAN_DAYS:
                    new_span = max(MIN_SPAN_DAYS, span_days // 2)
                    logger.debug(
                        f"Capped at {result_count} rows, shrinking span: {span_days}d → {new_span}d"
                    )
                    span_days = new_span
                    # Don't move window, retry with smaller span
                    continue
                else:
                    # Already at minimum (1 day) - accept with warning
                    date_str = self._format_date_for_api(window_end)
                    capped_single_days.append(date_str)
                    logger.warning(
                        f"⚠️  Single day [{date_str}] capped at {result_count} rows. "
                        f"Results may be incomplete."
                    )
                    # Accept results and move on
                    for row in results:
                        key = self._get_row_key(row)
                        if key not in seen_gins:
                            seen_gins.add(key)
                            all_results.append(row)
                            unique_count += 1
                    
                    # Move window back by 1 day
                    window_end = window_start - timedelta(days=1)
            
            elif result_count < LOW_THRESHOLD:
                # Sparse results - accept and expand window for next iteration
                for row in results:
                    key = self._get_row_key(row)
                    if key not in seen_gins:
                        seen_gins.add(key)
                        all_results.append(row)
                        unique_count += 1
                
                # Expand span for next iteration
                new_span = min(MAX_SPAN_DAYS, span_days * 2)
                if new_span != span_days:
                    logger.debug(
                        f"Sparse ({result_count} rows), expanding span: {span_days}d → {new_span}d"
                    )
                    span_days = new_span
                
                # Move window back
                window_end = window_start - timedelta(days=1)
            
            else:
                # Good result count (400-1999) - accept and move on
                for row in results:
                    key = self._get_row_key(row)
                    if key not in seen_gins:
                        seen_gins.add(key)
                        all_results.append(row)
                        unique_count += 1
                
                # Move window back
                window_end = window_start - timedelta(days=1)
            
            # Early stopping if we have enough results
            if max_results and unique_count >= max_results:
                logger.info(
                    f"Reached max_results ({max_results}) after {total_api_calls} API calls. "
                    f"Stopping early."
                )
                break
        
        # Calculate and log metrics
        avg_rows = sum(rows_per_call) / len(rows_per_call) if rows_per_call else 0
        min_window = min(window_sizes) if window_sizes else 0
        max_window = max(window_sizes) if window_sizes else 0
        
        logger.info(
            f"Sliding window search complete:\n"
            f"  • Total API calls: {total_api_calls}\n"
            f"  • Unique records: {unique_count}\n"
            f"  • Avg rows/call: {avg_rows:.1f}\n"
            f"  • Window size range: {min_window}-{max_window} days\n"
            f"  • Capped single days: {len(capped_single_days)}"
        )
        
        if capped_single_days:
            logger.warning(
                f"⚠️  {len(capped_single_days)} single days hit the 2000-row cap: "
                f"{capped_single_days[:5]}{'...' if len(capped_single_days) > 5 else ''}"
            )
        
        return all_results

    def _get_row_key(self, row: dict[str, Any]) -> str:
        """Get unique key for a row (gin or composite fallback)."""
        gin = row.get("gin")
        if gin:
            return str(gin)
        
        # Fallback to composite key
        return "|".join([
            str(row.get("inst_num", "")),
            str(row.get("party_name", "")),
            str(row.get("cross_party_name", "")),
            str(row.get("file_date", "")),
            str(row.get("direction", "")),
        ])

    def _dedupe_results(
        self,
        results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Deduplicate results using `gin` (global identifier) as primary key.
        
        Falls back to composite key if gin is not available:
        (inst_num, party_name, cross_party_name, file_date, direction)
        
        Args:
            results: List of result dictionaries
            
        Returns:
            List of unique result dictionaries
        """
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        duplicates = 0
        
        for row in results:
            key = self._get_row_key(row)
            
            if key not in seen:
                seen.add(key)
                unique.append(row)
            else:
                duplicates += 1
        
        if duplicates > 0:
            logger.debug(f"Removed {duplicates} duplicate records in final dedupe")
        
        return unique

    def _parse_response(
        self,
        response: requests.Response,
    ) -> list[dict[str, Any]]:
        """
        Parse the API response, handling both JSON and HTML.
        
        Args:
            response: HTTP response object
            
        Returns:
            List of result dictionaries
        """
        content_type = response.headers.get("Content-Type", "")
        response_text = response.text.strip()
        
        # Handle empty response (no results)
        if not response_text or response_text == '""':
            return []
        
        # Try JSON first (preferred)
        if "application/json" in content_type or response_text.startswith("["):
            try:
                data = response.json()
                
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict):
                    # Check for error response
                    if "Error" in data or "error" in data:
                        error_msg = data.get("Error") or data.get("error")
                        logger.warning(f"API returned error: {error_msg}")
                        return []
                    # Check for wrapped results
                    if "results" in data:
                        return data["results"]
                    if "data" in data:
                        return data["data"]
                    return []
                elif isinstance(data, str):
                    # API returns empty string "" when no results
                    if not data:
                        return []
                    logger.debug(f"API returned string response: {data[:100]}")
                    return []
                else:
                    logger.warning(f"Unexpected JSON response type: {type(data)}")
                    return []
                    
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse JSON response: {e}")
                # Fall through to HTML parsing
        
        # Fallback: try to parse as HTML
        if "text/html" in content_type:
            logger.debug("Response is HTML, attempting HTML parsing")
            return self._parse_html_results(response.text)
        
        logger.warning(f"Unknown response content type: {content_type}")
        return []

    def _parse_html_results(self, html: str) -> list[dict[str, Any]]:
        """
        Fallback HTML parser for non-JSON responses.
        
        Args:
            html: HTML content
            
        Returns:
            List of result dictionaries (empty if parsing fails)
        """
        try:
            from bs4 import BeautifulSoup
            
            soup = BeautifulSoup(html, "lxml")
            
            # Look for results table
            table = soup.find("table", {"id": re.compile(r"results|grid", re.I)})
            if not table:
                # Check for no results message
                if re.search(r"no\s+records?\s+found", html, re.I):
                    return []
                logger.warning("Could not find results table in HTML")
                return []
            
            results = []
            rows = table.find_all("tr")[1:]  # Skip header
            
            for row in rows:
                cells = row.find_all("td")
                if len(cells) >= 5:
                    results.append({
                        "inst_num": cells[0].get_text(strip=True),
                        "file_date": cells[1].get_text(strip=True),
                        "instrument_type": cells[2].get_text(strip=True),
                        "book_reel": cells[3].get_text(strip=True),
                        "page": cells[4].get_text(strip=True),
                        "party_name": cells[5].get_text(strip=True) if len(cells) > 5 else "",
                        "cross_party_name": cells[6].get_text(strip=True) if len(cells) > 6 else "",
                        "direction": "From",  # Default assumption
                    })
            
            return results
            
        except Exception as e:
            logger.warning(f"HTML parsing failed: {e}")
            return []

    def _parse_result_rows(
        self,
        rows: list[dict[str, Any]],
    ) -> list[Record]:
        """
        Parse all result rows into Record objects.
        
        Args:
            rows: List of result dictionaries from API
            
        Returns:
            List of parsed Record objects
        """
        records = []
        parse_errors = 0
        
        for row in rows:
            try:
                record = self._row_to_record(row)
                if record:
                    records.append(record)
            except Exception as e:
                parse_errors += 1
                logger.debug(f"Failed to parse row: {e}")
        
        if parse_errors > 0:
            logger.warning(f"Failed to parse {parse_errors} rows")
        
        return records

    def _row_to_record(self, row: dict[str, Any]) -> Optional[Record]:
        """
        Convert a single API result row to a Record object.
        
        Maps Seminole JSON fields to NC dataset schema.
        
        Args:
            row: Dictionary from API response
            
        Returns:
            Record object or None if required fields missing
        """
        # Extract instrument number (required)
        inst_num = row.get("inst_num")
        if not inst_num:
            logger.debug("Skipping row without inst_num")
            return None
        
        # Extract book/page
        book = row.get("book_reel")
        page = row.get("page")
        
        # Extract document type
        doc_type = row.get("instrument_type")
        
        # Extract book type (prefer book_description)
        book_type = row.get("book_description") or row.get("book_name")
        
        # Parse date
        file_date = row.get("file_date")
        normalized_date = self._parse_date(file_date) if file_date else None
        
        # Extract and map names based on direction
        party_name = row.get("party_name", "")
        cross_party_name = row.get("cross_party_name", "")
        direction = row.get("direction", "")
        
        grantors, grantees = self._map_parties(party_name, cross_party_name, direction)
        
        # Extract consideration (if present)
        consideration = None
        consideration_val = row.get("consideration_value")
        if consideration_val:
            try:
                consideration = float(str(consideration_val).replace(",", "").replace("$", ""))
            except (ValueError, TypeError):
                pass
        
        return Record(
            instrument_number=str(inst_num).strip(),
            parcel_number=row.get("parcel_id"),
            county=self.COUNTY,
            state=self.STATE,
            book=str(book).strip() if book else None,
            page=str(page).strip() if page else None,
            doc_type=doc_type,
            doc_category=self._categorize_doc_type(doc_type),
            original_doc_type=doc_type,
            book_type=book_type,
            grantors=tuple(grantors),
            grantees=tuple(grantees),
            date=normalized_date,
            consideration=consideration,
        )

    def _map_parties(
        self,
        party_name: str,
        cross_party_name: str,
        direction: str,
    ) -> tuple[list[str], list[str]]:
        """
        Map party names to grantors/grantees based on direction.
        
        Args:
            party_name: Primary party name
            cross_party_name: Cross-referenced party name
            direction: "From" or "To"
            
        Returns:
            Tuple of (grantors, grantees) lists
        """
        # Normalize names to uppercase, trim whitespace
        party = self._normalize_name(party_name)
        cross_party = self._normalize_name(cross_party_name)
        
        grantors: list[str] = []
        grantees: list[str] = []
        
        direction_lower = direction.lower().strip() if direction else ""
        
        if direction_lower == "from":
            # party_name is grantor, cross_party_name is grantee
            if party:
                grantors.append(party)
            if cross_party:
                grantees.append(cross_party)
        elif direction_lower == "to":
            # party_name is grantee, cross_party_name is grantor
            if cross_party:
                grantors.append(cross_party)
            if party:
                grantees.append(party)
        else:
            # Unknown direction - log warning and use reasonable default
            if direction:
                logger.warning(f"Unknown direction '{direction}', defaulting to From")
            # Default: treat as "From"
            if party:
                grantors.append(party)
            if cross_party:
                grantees.append(cross_party)
        
        return grantors, grantees

    def _normalize_name(self, name: Optional[str]) -> Optional[str]:
        """
        Normalize a name to uppercase with trimmed whitespace.
        
        Args:
            name: Name string to normalize
            
        Returns:
            Normalized name or None if empty
        """
        if not name:
            return None
        
        normalized = name.strip().upper()
        # Collapse multiple spaces
        normalized = re.sub(r"\s+", " ", normalized)
        
        return normalized if normalized else None

    def _categorize_doc_type(self, doc_type: Optional[str]) -> Optional[str]:
        """
        Categorize document type into a standard category.
        
        Maps raw document types to normalized categories like:
        deed, mortgage, lien, release, plat, easement, lease, misc
        
        Args:
            doc_type: Raw document type string
            
        Returns:
            Lowercase category string or None
        """
        if not doc_type:
            return None
        
        doc_upper = doc_type.upper()
        
        # Deed types
        if any(kw in doc_upper for kw in ["DEED", "WARRANTY", "QUITCLAIM", "QUIT CLAIM"]):
            return "deed"
        
        # Mortgage types
        if any(kw in doc_upper for kw in ["MORTGAGE", "MTG"]):
            return "mortgage"
        
        # Lien types
        if any(kw in doc_upper for kw in ["LIEN", "LIS PENDENS"]):
            return "lien"
        
        # Release/satisfaction types
        if any(kw in doc_upper for kw in ["RELEASE", "SATISFACTION", "DISCHARGE"]):
            return "release"
        
        # Plat types
        if "PLAT" in doc_upper:
            return "plat"
        
        # Easement types
        if "EASEMENT" in doc_upper:
            return "easement"
        
        # Lease types
        if "LEASE" in doc_upper:
            return "lease"
        
        # Assignment types
        if "ASSIGNMENT" in doc_upper:
            return "assignment"
        
        # Default to misc
        return "misc"

    def _parse_date(self, date_str: str) -> Optional[str]:
        """
        Parse date string and return ISO 8601 format with timezone.
        
        Handles formats like "6/1/2007 2:58:08 PM"
        
        Args:
            date_str: Date string from API
            
        Returns:
            ISO 8601 formatted date string or None
        """
        if not date_str:
            return None
        
        # Common date formats from Seminole API
        formats = [
            "%m/%d/%Y %I:%M:%S %p",  # 6/1/2007 2:58:08 PM
            "%m/%d/%Y %H:%M:%S",      # 6/1/2007 14:58:08
            "%m/%d/%Y",               # 6/1/2007
            "%Y-%m-%d %H:%M:%S",      # 2007-06-01 14:58:08
            "%Y-%m-%d",               # 2007-06-01
        ]
        
        for fmt in formats:
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                # Localize to Seminole County timezone (America/New_York)
                dt_local = dt.replace(tzinfo=SEMINOLE_TZ)
                return dt_local.isoformat()
            except ValueError:
                continue
        
        logger.debug(f"Could not parse date: {date_str}")
        return None

    def iter_records_by_name(
        self,
        name: str,
        date_start: str = "1/1/2020",
        date_end: Optional[str] = None,
        max_results: Optional[int] = None,
        chunked: bool = True,
    ) -> Iterator[dict[str, Any]]:
        """
        Stream records by name using a generator (memory-efficient).
        
        This is the PRIMARY method for production use. It yields records
        one-by-one without accumulating them in memory.
        
        Algorithm:
        1. Run adaptive sliding window search
        2. For each fetched row:
           - Compute dedupe key (gin or fallback)
           - Skip if already seen
           - Convert row → Record → dict
           - Validate schema
           - Yield immediately
        
        Args:
            name: Name to search for
            date_start: Start date for search range
            date_end: End date for search range (default: today)
            max_results: Stop after yielding this many records (None for all)
            chunked: If True, use adaptive sliding window
            
        Yields:
            Record dictionaries one at a time
        """
        self._start_time = time.time()
        self._request_count = 0
        self._chunked_mode = chunked
        
        logger.info(f"Starting streaming search for name: '{name}' (chunked={chunked})")
        
        # Default end date to today
        if date_end is None:
            date_end = datetime.now(SEMINOLE_TZ).strftime("%m/%d/%Y")
        
        # Ensure session is warmed up
        self._warmup_session()
        
        # Parse date strings
        start_dt = self._parse_date_str(date_start)
        end_dt = self._parse_date_str(date_end)
        
        # Dedup tracking (only state we keep in memory)
        seen_gins: set[str] = set()
        yielded_count = 0
        skipped_invalid = 0
        
        # Metrics
        total_api_calls = 0
        capped_single_days: list[str] = []
        
        # Sliding window state
        span_days = DEFAULT_SPAN_DAYS
        window_end = end_dt
        
        logger.info(
            f"Streaming window search: "
            f"{self._format_date_for_api(start_dt)} to {self._format_date_for_api(end_dt)}"
        )
        
        while window_end >= start_dt:
            # Safety check
            if self._request_count >= MAX_API_REQUESTS:
                logger.warning(
                    f"⚠️  Reached max API requests ({MAX_API_REQUESTS}). "
                    f"Stopping with {yielded_count} yielded records."
                )
                break
            
            # Calculate window_start, clamped to start_dt
            window_start = window_end - timedelta(days=span_days - 1)
            if window_start < start_dt:
                window_start = start_dt
            
            # Fetch results for this window
            if chunked:
                results = self._search_range(name, window_start, window_end, log_request=False)
            else:
                # Non-chunked: single request for entire range
                results = self._search_range(name, start_dt, end_dt, log_request=True)
                # Process all results and exit loop
                for row in results:
                    key = self._get_row_key(row)
                    if key in seen_gins:
                        continue
                    seen_gins.add(key)
                    
                    record = self._row_to_record(row)
                    if record is None:
                        continue
                    
                    record_dict = record.to_dict()
                    if validate_record(record_dict):
                        yield record_dict
                        yielded_count += 1
                        if max_results and yielded_count >= max_results:
                            break
                    else:
                        skipped_invalid += 1
                break  # Exit loop for non-chunked mode
            
            result_count = len(results)
            total_api_calls += 1
            
            # Log progress
            logger.info(
                f"Window #{total_api_calls}: [{self._format_date_for_api(window_start)} - "
                f"{self._format_date_for_api(window_end)}] span={span_days}d → {result_count} rows"
            )
            
            # Decide action based on result count
            if result_count >= HIGH_THRESHOLD:
                # Hit cap - shrink window
                if span_days > MIN_SPAN_DAYS:
                    new_span = max(MIN_SPAN_DAYS, span_days // 2)
                    logger.debug(f"Capped, shrinking span: {span_days}d → {new_span}d")
                    span_days = new_span
                    continue  # Retry with smaller span
                else:
                    # Already at minimum - accept with warning
                    date_str = self._format_date_for_api(window_end)
                    capped_single_days.append(date_str)
                    logger.warning(f"⚠️  Single day [{date_str}] capped at {result_count} rows.")
            elif result_count < LOW_THRESHOLD:
                # Sparse - expand for next iteration
                new_span = min(MAX_SPAN_DAYS, span_days * 2)
                if new_span != span_days:
                    logger.debug(f"Sparse, expanding span: {span_days}d → {new_span}d")
                    span_days = new_span
            
            # Process and yield results from this window
            for row in results:
                key = self._get_row_key(row)
                if key in seen_gins:
                    continue
                seen_gins.add(key)
                
                record = self._row_to_record(row)
                if record is None:
                    continue
                
                record_dict = record.to_dict()
                if validate_record(record_dict):
                    yield record_dict
                    yielded_count += 1
                    
                    if max_results and yielded_count >= max_results:
                        logger.info(f"Reached max_results ({max_results}). Stopping.")
                        # Log final metrics before returning
                        elapsed = time.time() - self._start_time
                        logger.info(
                            f"Streaming complete: {yielded_count} records in {elapsed:.1f}s "
                            f"({self._request_count} API calls)"
                        )
                        return
                else:
                    skipped_invalid += 1
            
            # Move window back
            window_end = window_start - timedelta(days=1)
        
        # Final metrics
        elapsed = time.time() - self._start_time
        records_per_min = (yielded_count / elapsed * 60) if elapsed > 0 else 0
        
        logger.info(
            f"Streaming complete:\n"
            f"  • Records yielded: {yielded_count}\n"
            f"  • Skipped invalid: {skipped_invalid}\n"
            f"  • API calls: {self._request_count}\n"
            f"  • Duration: {elapsed:.1f}s ({records_per_min:.1f} records/min)"
        )
        
        if capped_single_days:
            logger.warning(
                f"⚠️  {len(capped_single_days)} single days hit 2000-row cap: "
                f"{capped_single_days[:5]}{'...' if len(capped_single_days) > 5 else ''}"
            )

    def close(self) -> None:
        """Close the scraper and release resources."""
        self.session.close()

    def __enter__(self) -> SeminoleScraper:
        """Enter context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager."""
        self.close()


def run_test_searches(
    scraper: SeminoleScraper,
    output_path: str,
    chunked: bool = True,
) -> dict[str, Any]:
    """
    Run test searches with multiple names - STREAMING to JSON array.
    
    Output format: JSON array file (valid JSON that can be parsed with json.load()).
    Records are streamed directly to disk without accumulating in memory.
    
    Args:
        scraper: SeminoleScraper instance
        output_path: Path for output JSON file
        chunked: Whether to use chunked mode
        
    Returns:
        Dictionary with test summary (for logging only, not in output)
    """
    # Test names - common, full name, and rare
    test_names = [
        "Smith",           # Common name - likely >2000 results
        "Johnson Michael", # Common full name
        "Xyzabc",          # Rare/unlikely name - should have no results
    ]
    
    # Track summary for logging (NOT included in output)
    summary = {
        "test_names": test_names,
        "searches": [],
    }
    
    # Stream ALL records to single JSON array file
    with JsonArrayWriter(output_path) as writer:
        for name in test_names:
            logger.info(f"\n{'='*50}")
            logger.info(f"Testing search for: {name} (chunked={chunked})")
            logger.info(f"{'='*50}")
            
            search_info = {
                "name": name,
                "record_count": 0,
                "error": None,
            }
            
            try:
                # Stream records directly to disk
                count = 0
                for record_dict in scraper.iter_records_by_name(name, chunked=chunked):
                    writer.write_record(record_dict)
                    count += 1
                    
                    # Log first few for debugging
                    if count <= 3:
                        logger.debug(
                            f"  Record {count}: {record_dict.get('instrument_number')} - "
                            f"{record_dict.get('doc_type')}"
                        )
                
                search_info["record_count"] = count
                logger.info(f"Wrote {count} records for '{name}'")
                
            except SeminoleScraperError as e:
                search_info["error"] = str(e)
                logger.error(f"Search failed for '{name}': {e}")
            
            summary["searches"].append(search_info)
            
            # Delay between test searches
            time.sleep(3)
    
    logger.info(f"Wrote {writer.record_count} total records to {output_path}")
    
    return summary


def main():
    """Main entry point for the Seminole scraper CLI."""
    parser = argparse.ArgumentParser(
        description="Search Seminole County property records (JSON array streaming output)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.seminole_scraper --name "John Smith" --output results.json
  python -m src.seminole_scraper --name "Smith" --chunked --output outputs/smith.json
  python -m src.seminole_scraper --name "Smith" --no-chunked --output outputs/smith_capped.json
  python -m src.seminole_scraper --test --output outputs/test.json

Notes:
  Output is JSON array format (valid JSON parseable with json.load()).
  The CriteriaSearch API returns at most 2000 rows per request.
  Use --chunked (default) to use adaptive sliding window search and retrieve more results.
  Use --no-chunked to get raw server response (max 2000).
        """
    )
    
    parser.add_argument(
        "--name", "-n",
        help="Name to search for"
    )
    
    parser.add_argument(
        "--output", "-o",
        default="outputs/seminole_results.json",
        help="Path for output JSON file (default: outputs/seminole_results.json)"
    )
    
    parser.add_argument(
        "--max-results",
        type=int,
        help="Maximum number of results to return"
    )
    
    parser.add_argument(
        "--test",
        action="store_true",
        help="Run test searches with predefined names"
    )
    
    parser.add_argument(
        "--chunked",
        action="store_true",
        default=True,
        dest="chunked",
        help="Use adaptive sliding window search to bypass 2000-row cap (default: enabled)"
    )
    
    parser.add_argument(
        "--no-chunked",
        action="store_false",
        dest="chunked",
        help="Disable chunking - single request, max 2000 rows"
    )
    
    parser.add_argument(
        "--date-start",
        default="1/1/1913",
        help="Start date for search (default: 1/1/1913)"
    )
    
    parser.add_argument(
        "--date-end",
        help="End date for search (default: today)"
    )
    
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Request timeout in seconds (default: 120)"
    )
    
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level (default: INFO)"
    )
    
    args = parser.parse_args()
    
    # Setup logging
    log_level = getattr(logging, args.log_level)
    setup_logging(level=log_level)
    
    # Validate arguments
    if not args.name and not args.test:
        parser.error("Either --name or --test must be specified")
    
    # Create scraper
    with SeminoleScraper(timeout=args.timeout) as scraper:
        if args.test:
            # Run test searches (streaming to JSON array)
            summary = run_test_searches(scraper, args.output, chunked=args.chunked)
            
            # Print summary to console (not in output file)
            print(f"\n{'='*60}")
            print("TEST SEARCH SUMMARY")
            print(f"{'='*60}")
            print(f"Chunked mode: {args.chunked}")
            print(f"Output format: JSON array (streaming)")
            
            total_records = 0
            for search in summary["searches"]:
                status = "✓" if not search["error"] else "✗"
                count = search["record_count"]
                name = search["name"]
                total_records += count
                print(f"{status} '{name}': {count} records")
            
            print(f"\nTotal records in output: {total_records}")
            print(f"Results written to: {args.output}")
            
        else:
            # Single name search - STREAMING to JSON array
            try:
                # Stream records directly to JSON array file
                record_count = 0
                first_records: list[dict] = []
                
                with JsonArrayWriter(args.output) as writer:
                    for record_dict in scraper.iter_records_by_name(
                        args.name,
                        max_results=args.max_results,
                        date_start=args.date_start,
                        date_end=args.date_end,
                        chunked=args.chunked,
                    ):
                        writer.write_record(record_dict)
                        record_count += 1
                        
                        # Keep first 5 for display
                        if len(first_records) < 5:
                            first_records.append(record_dict)
                
                # Print summary to console (not in output file)
                print(f"\n{'='*60}")
                print(f"Search Results for: {args.name}")
                print(f"{'='*60}")
                print(f"Chunked mode: {args.chunked}")
                print(f"Output format: JSON array (streaming)")
                print(f"Records found: {record_count}")
                
                if first_records:
                    print(f"\nFirst {len(first_records)} records:")
                    for i, rec in enumerate(first_records, 1):
                        print(f"  {i}. {rec.get('instrument_number')} - {rec.get('doc_type')}")
                
                print(f"\nResults written to: {args.output}")
                
            except SeminoleScraperError as e:
                logger.error(f"Search failed: {e}")
                sys.exit(1)


if __name__ == "__main__":
    main()
