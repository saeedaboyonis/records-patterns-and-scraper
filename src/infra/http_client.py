"""
HTTP client with retry logic and session management.

This module provides a robust HTTP client for web scraping with:
- Connection pooling
- Automatic retries with exponential backoff
- Request/response logging
- Timeout handling
- User-agent rotation
"""

from __future__ import annotations

import time
from typing import Any, Optional
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from .logging import get_logger


logger = get_logger(__name__)


class HttpClientError(Exception):
    """Exception raised for HTTP client errors."""
    pass


class HttpClient:
    """
    Robust HTTP client with retry logic and session management.
    
    This class provides a production-ready HTTP client suitable for
    web scraping with:
    - Automatic session management with connection pooling
    - Retry logic with exponential backoff
    - Request/response logging
    - Configurable timeouts
    - User-agent management
    
    Example:
        >>> client = HttpClient()
        >>> response = client.get("https://example.com")
        >>> print(response.text)
    """
    
    # Default user agents for rotation
    DEFAULT_USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    ]
    
    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_backoff: float = 1.0,
        user_agent: Optional[str] = None,
        verify_ssl: bool = True,
    ):
        """
        Initialize the HTTP client.
        
        Args:
            base_url: Base URL for all requests
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
            retry_backoff: Base backoff time for retries
            user_agent: User-Agent header (uses default if not specified)
            verify_ssl: Whether to verify SSL certificates
        """
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.user_agent = user_agent or self.DEFAULT_USER_AGENTS[0]
        self.verify_ssl = verify_ssl
        
        self._session: Optional[requests.Session] = None
        self._request_count = 0
        self._last_request_time: Optional[float] = None

    def _get_session(self) -> requests.Session:
        """
        Get or create the HTTP session.
        
        Returns:
            Configured requests Session
        """
        if self._session is None:
            self._session = requests.Session()
            
            # Configure retry strategy
            retry_strategy = Retry(
                total=self.max_retries,
                backoff_factor=self.retry_backoff,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["HEAD", "GET", "POST", "OPTIONS"],
            )
            
            adapter = HTTPAdapter(
                max_retries=retry_strategy,
                pool_connections=10,
                pool_maxsize=10,
            )
            
            self._session.mount("http://", adapter)
            self._session.mount("https://", adapter)
            
            # Set default headers
            self._session.headers.update({
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate",
                "Connection": "keep-alive",
            })
        
        return self._session

    def _build_url(self, endpoint: str) -> str:
        """Build full URL from endpoint."""
        if self.base_url:
            return urljoin(self.base_url, endpoint)
        return endpoint

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((requests.RequestException, ConnectionError)),
    )
    def get(
        self,
        url: str,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        **kwargs: Any,
    ) -> requests.Response:
        """
        Make a GET request.
        
        Args:
            url: URL or endpoint to request
            params: Query parameters
            headers: Additional headers
            **kwargs: Additional arguments passed to requests
            
        Returns:
            Response object
            
        Raises:
            HttpClientError: If request fails after retries
        """
        full_url = self._build_url(url)
        session = self._get_session()
        
        try:
            logger.debug(f"GET {full_url}")
            
            response = session.get(
                full_url,
                params=params,
                headers=headers,
                timeout=self.timeout,
                verify=self.verify_ssl,
                **kwargs,
            )
            
            self._request_count += 1
            self._last_request_time = time.time()
            
            logger.debug(f"Response: {response.status_code} ({len(response.content)} bytes)")
            
            response.raise_for_status()
            return response
            
        except requests.RequestException as e:
            logger.error(f"GET request failed: {full_url} - {e}")
            raise HttpClientError(f"Request failed: {e}") from e

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((requests.RequestException, ConnectionError)),
    )
    def post(
        self,
        url: str,
        data: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        **kwargs: Any,
    ) -> requests.Response:
        """
        Make a POST request.
        
        Args:
            url: URL or endpoint to request
            data: Form data
            json: JSON data
            headers: Additional headers
            **kwargs: Additional arguments passed to requests
            
        Returns:
            Response object
            
        Raises:
            HttpClientError: If request fails after retries
        """
        full_url = self._build_url(url)
        session = self._get_session()
        
        try:
            logger.debug(f"POST {full_url}")
            
            response = session.post(
                full_url,
                data=data,
                json=json,
                headers=headers,
                timeout=self.timeout,
                verify=self.verify_ssl,
                **kwargs,
            )
            
            self._request_count += 1
            self._last_request_time = time.time()
            
            logger.debug(f"Response: {response.status_code} ({len(response.content)} bytes)")
            
            response.raise_for_status()
            return response
            
        except requests.RequestException as e:
            logger.error(f"POST request failed: {full_url} - {e}")
            raise HttpClientError(f"Request failed: {e}") from e

    def get_text(
        self,
        url: str,
        params: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> str:
        """
        Make a GET request and return response text.
        
        Args:
            url: URL or endpoint to request
            params: Query parameters
            **kwargs: Additional arguments
            
        Returns:
            Response text content
        """
        response = self.get(url, params=params, **kwargs)
        return response.text

    def get_json(
        self,
        url: str,
        params: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Any:
        """
        Make a GET request and return JSON response.
        
        Args:
            url: URL or endpoint to request
            params: Query parameters
            **kwargs: Additional arguments
            
        Returns:
            Parsed JSON response
        """
        response = self.get(url, params=params, **kwargs)
        return response.json()

    def close(self) -> None:
        """Close the HTTP session."""
        if self._session:
            self._session.close()
            self._session = None

    def __enter__(self) -> HttpClient:
        """Enter context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager."""
        self.close()

    @property
    def request_count(self) -> int:
        """Get total number of requests made."""
        return self._request_count

    def get_stats(self) -> dict[str, Any]:
        """Get client statistics."""
        return {
            "request_count": self._request_count,
            "last_request_time": self._last_request_time,
            "base_url": self.base_url,
        }
