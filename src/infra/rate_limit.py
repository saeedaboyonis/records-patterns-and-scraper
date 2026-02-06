"""
Rate limiting utilities.

This module provides rate limiting functionality to ensure respectful
interaction with external services and APIs.
"""

from __future__ import annotations

import time
import threading
from collections import deque
from typing import Optional

from .logging import get_logger


logger = get_logger(__name__)


class RateLimiter:
    """
    Token bucket rate limiter for controlling request frequency.
    
    This class implements a token bucket algorithm to limit the rate
    of operations. It supports:
    - Configurable requests per second
    - Minimum delay between requests
    - Thread-safe operation
    - Blocking and non-blocking modes
    
    Example:
        >>> limiter = RateLimiter(requests_per_second=2.0)
        >>> for url in urls:
        ...     limiter.wait()  # Blocks if needed
        ...     response = client.get(url)
    """
    
    def __init__(
        self,
        requests_per_second: float = 1.0,
        min_delay: float = 0.5,
        burst_size: int = 1,
    ):
        """
        Initialize the rate limiter.
        
        Args:
            requests_per_second: Maximum requests allowed per second
            min_delay: Minimum delay between requests in seconds
            burst_size: Maximum number of requests allowed in a burst
        """
        self.requests_per_second = requests_per_second
        self.min_delay = min_delay
        self.burst_size = burst_size
        
        self._interval = 1.0 / requests_per_second
        self._tokens = float(burst_size)
        self._last_update = time.monotonic()
        self._last_request = 0.0
        self._lock = threading.Lock()
        
        # Statistics
        self._total_requests = 0
        self._total_wait_time = 0.0

    def _refill_tokens(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_update
        self._tokens = min(
            self.burst_size,
            self._tokens + elapsed * self.requests_per_second
        )
        self._last_update = now

    def wait(self) -> float:
        """
        Wait until a request is allowed.
        
        This method blocks until the rate limit allows another request.
        
        Returns:
            Time waited in seconds
        """
        with self._lock:
            self._refill_tokens()
            
            wait_time = 0.0
            
            # Wait for token availability
            if self._tokens < 1.0:
                wait_time = (1.0 - self._tokens) * self._interval
            
            # Enforce minimum delay
            now = time.monotonic()
            since_last = now - self._last_request
            if since_last < self.min_delay:
                additional_wait = self.min_delay - since_last
                wait_time = max(wait_time, additional_wait)
            
            if wait_time > 0:
                logger.debug(f"Rate limiter waiting {wait_time:.3f}s")
                time.sleep(wait_time)
                self._refill_tokens()
            
            # Consume token
            self._tokens -= 1.0
            self._last_request = time.monotonic()
            
            # Update statistics
            self._total_requests += 1
            self._total_wait_time += wait_time
            
            return wait_time

    def try_acquire(self) -> bool:
        """
        Try to acquire a request slot without blocking.
        
        Returns:
            True if a request is allowed, False otherwise
        """
        with self._lock:
            self._refill_tokens()
            
            now = time.monotonic()
            since_last = now - self._last_request
            
            if self._tokens >= 1.0 and since_last >= self.min_delay:
                self._tokens -= 1.0
                self._last_request = now
                self._total_requests += 1
                return True
            
            return False

    def reset(self) -> None:
        """Reset the rate limiter to initial state."""
        with self._lock:
            self._tokens = float(self.burst_size)
            self._last_update = time.monotonic()
            self._last_request = 0.0

    def get_stats(self) -> dict[str, float]:
        """
        Get rate limiter statistics.
        
        Returns:
            Dictionary with statistics
        """
        with self._lock:
            return {
                "total_requests": self._total_requests,
                "total_wait_time": self._total_wait_time,
                "average_wait_time": (
                    self._total_wait_time / self._total_requests
                    if self._total_requests > 0
                    else 0.0
                ),
                "current_tokens": self._tokens,
            }


class SlidingWindowRateLimiter:
    """
    Sliding window rate limiter for more accurate rate limiting.
    
    This implementation tracks individual request timestamps
    to provide more accurate rate limiting than token bucket.
    """
    
    def __init__(
        self,
        max_requests: int = 10,
        window_seconds: float = 60.0,
        min_delay: float = 0.5,
    ):
        """
        Initialize the sliding window rate limiter.
        
        Args:
            max_requests: Maximum requests allowed in the window
            window_seconds: Window size in seconds
            min_delay: Minimum delay between requests
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.min_delay = min_delay
        
        self._requests: deque[float] = deque()
        self._lock = threading.Lock()

    def _cleanup_old_requests(self, now: float) -> None:
        """Remove requests outside the current window."""
        cutoff = now - self.window_seconds
        while self._requests and self._requests[0] < cutoff:
            self._requests.popleft()

    def wait(self) -> float:
        """
        Wait until a request is allowed.
        
        Returns:
            Time waited in seconds
        """
        with self._lock:
            now = time.monotonic()
            self._cleanup_old_requests(now)
            
            wait_time = 0.0
            
            # Check if window is full
            if len(self._requests) >= self.max_requests:
                oldest = self._requests[0]
                wait_time = (oldest + self.window_seconds) - now
            
            # Enforce minimum delay
            if self._requests:
                since_last = now - self._requests[-1]
                if since_last < self.min_delay:
                    additional_wait = self.min_delay - since_last
                    wait_time = max(wait_time, additional_wait)
            
            if wait_time > 0:
                logger.debug(f"Sliding window limiter waiting {wait_time:.3f}s")
                time.sleep(wait_time)
                now = time.monotonic()
                self._cleanup_old_requests(now)
            
            self._requests.append(time.monotonic())
            return wait_time

    def get_remaining_requests(self) -> int:
        """
        Get the number of remaining requests in the current window.
        
        Returns:
            Number of remaining requests allowed
        """
        with self._lock:
            self._cleanup_old_requests(time.monotonic())
            return max(0, self.max_requests - len(self._requests))


class AdaptiveRateLimiter:
    """
    Adaptive rate limiter that adjusts based on response times.
    
    This limiter automatically adjusts the rate based on server
    response times to be more respectful during high load.
    """
    
    def __init__(
        self,
        initial_rate: float = 1.0,
        min_rate: float = 0.1,
        max_rate: float = 10.0,
        target_response_time: float = 1.0,
    ):
        """
        Initialize the adaptive rate limiter.
        
        Args:
            initial_rate: Initial requests per second
            min_rate: Minimum requests per second
            max_rate: Maximum requests per second
            target_response_time: Target response time in seconds
        """
        self.min_rate = min_rate
        self.max_rate = max_rate
        self.target_response_time = target_response_time
        
        self._current_rate = initial_rate
        self._limiter = RateLimiter(requests_per_second=initial_rate)
        self._response_times: deque[float] = deque(maxlen=10)
        self._lock = threading.Lock()

    def wait(self) -> float:
        """Wait until a request is allowed."""
        return self._limiter.wait()

    def record_response_time(self, response_time: float) -> None:
        """
        Record a response time and adjust rate accordingly.
        
        Args:
            response_time: Response time in seconds
        """
        with self._lock:
            self._response_times.append(response_time)
            
            if len(self._response_times) >= 5:
                avg_response = sum(self._response_times) / len(self._response_times)
                
                if avg_response > self.target_response_time * 1.5:
                    # Slow down
                    new_rate = max(self.min_rate, self._current_rate * 0.8)
                elif avg_response < self.target_response_time * 0.5:
                    # Speed up
                    new_rate = min(self.max_rate, self._current_rate * 1.2)
                else:
                    return
                
                if new_rate != self._current_rate:
                    logger.info(
                        f"Adjusting rate: {self._current_rate:.2f} -> {new_rate:.2f} "
                        f"(avg response: {avg_response:.3f}s)"
                    )
                    self._current_rate = new_rate
                    self._limiter = RateLimiter(requests_per_second=new_rate)

    @property
    def current_rate(self) -> float:
        """Get the current request rate."""
        return self._current_rate
