"""
REXY RATE LIMITER
Tracks requests per WebSocket connection.
Uses a sliding window — counts only requests in the last 60 seconds.
No new dependencies needed — pure Python.
"""

import time
import logging
from collections import deque

from config import RATE_LIMIT_PER_MINUTE

logger = logging.getLogger("rexy.ratelimiter")


class RateLimiter:
    """
    One instance per WebSocket connection.
    Tracks timestamps of recent messages in a sliding window.

    How sliding window works:
    - Every message timestamp is added to a deque
    - Before checking, we remove timestamps older than 60 seconds
    - If remaining count >= limit → reject
    - This is fairer than a fixed window (which resets hard every minute)
    """

    def __init__(self, limit: int = RATE_LIMIT_PER_MINUTE):
        self.limit    = limit          # Max requests per 60 seconds
        self.window   = 60.0           # Window size in seconds
        self.requests = deque()        # Timestamps of recent requests

    def is_allowed(self) -> bool:
        """
        Call this for every incoming message.
        Returns True if allowed, False if rate limit exceeded.
        """
        now = time.time()

        # Remove timestamps outside the window
        while self.requests and self.requests[0] < now - self.window:
            self.requests.popleft()

        # Check if under limit
        if len(self.requests) >= self.limit:
            logger.warning(
                f"Rate limit hit: {len(self.requests)} requests "
                f"in last {int(self.window)}s (limit: {self.limit})"
            )
            return False

        # Record this request
        self.requests.append(now)
        return True

    def remaining(self) -> int:
        """How many requests are left in the current window."""
        now = time.time()
        while self.requests and self.requests[0] < now - self.window:
            self.requests.popleft()
        return max(0, self.limit - len(self.requests))