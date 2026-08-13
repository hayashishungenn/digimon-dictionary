"""HTTP request protection: timeout, retry with exponential backoff, rate
limiting, a descriptive User-Agent, and a content cache.

Implements the product spec §48 requirements. Concurrency is deliberately
conservative — we never hammer target sites.
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx

from .config import DEFAULT_MAX_RETRIES, DEFAULT_RATE_PER_SECOND, DEFAULT_TIMEOUT, DEFAULT_USER_AGENT

logger = logging.getLogger(__name__)


class TokenBucket:
    """Simple thread-safe token bucket for rate limiting."""

    def __init__(self, rate_per_second: float) -> None:
        self._rate = max(rate_per_second, 1e-6)
        self._capacity = self._rate
        self._tokens = self._capacity
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, block: bool = True) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(self._capacity, self._tokens + (now - self._updated) * self._rate)
                self._updated = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self._rate
            if not block:
                return
            time.sleep(wait)


def _backoff_delay(attempt: int, base: float = 0.8, max_delay: float = 20.0) -> float:
    """Exponential backoff with jitter: base * 2^attempt, capped, randomized."""
    delay = min(base * (2 ** attempt), max_delay)
    jitter = delay * (0.5 + random.random() * 0.5)
    return jitter


def _cache_key(url: str, params: dict[str, Any] | None) -> str:
    payload = json.dumps({"url": url, "params": params}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class FetchResult:
    url: str
    status_code: int
    content: bytes
    content_type: str | None
    from_cache: bool = False
    http_version: str | None = None

    @property
    def text(self) -> str:
        """Best-effort UTF-8 decode of content."""
        if self.content_type and "charset=" in self.content_type:
            charset = self.content_type.split("charset=")[-1].strip().strip('"')
            try:
                return self.content.decode(charset, errors="replace")
            except LookupError:
                pass
        return self.content.decode("utf-8", errors="replace")


class Fetcher:
    """Rate-limited, retrying, cached HTTP fetcher."""

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        rate_per_second: float = DEFAULT_RATE_PER_SECOND,
        user_agent: str = DEFAULT_USER_AGENT,
        cache_dir: Path | None = None,
        max_concurrency: int = 2,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._bucket = TokenBucket(rate_per_second)
        self._timeout = timeout
        self._max_retries = max_retries
        self._headers = {"User-Agent": user_agent}
        if headers:
            self._headers.update(headers)
        self._cache_dir = cache_dir
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers=self._headers,
            limits=httpx.Limits(max_connections=max_concurrency, max_keepalive_connections=max_concurrency),
        )
        self._last_request_at = 0.0
        self._lock = threading.Lock()

    # ---- cache helpers -------------------------------------------------
    def _cache_path(self, key: str) -> Path:
        assert self._cache_dir is not None
        return self._cache_dir / f"{key}.cache"

    def _read_cache(self, key: str) -> FetchResult | None:
        if self._cache_dir is None:
            return None
        path = self._cache_path(key)
        try:
            if not path.exists():
                return None
            meta = json.loads(path.read_text("utf-8"))
            content = bytes.fromhex(meta["content_hex"])
            return FetchResult(
                url=meta["url"],
                status_code=meta["status_code"],
                content=content,
                content_type=meta.get("content_type"),
                from_cache=True,
            )
        except (OSError, ValueError, KeyError):
            return None

    def _write_cache(self, key: str, result: FetchResult) -> None:
        if self._cache_dir is None:
            return
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            meta = {
                "url": result.url,
                "status_code": result.status_code,
                "content_type": result.content_type,
                "content_hex": result.content.hex(),
            }
            self._cache_path(key).write_text(json.dumps(meta), "utf-8")
        except OSError:
            logger.warning("Failed to write HTTP cache for %s", result.url)

    # ---- fetch ----------------------------------------------------------
    def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        use_cache: bool = True,
        max_retries: int | None = None,
    ) -> FetchResult:
        key = _cache_key(url, params)
        if use_cache:
            cached = self._read_cache(key)
            if cached is not None:
                return cached

        retries = max_retries if max_retries is not None else self._max_retries
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            self._bucket.acquire()
            try:
                resp = self._client.get(url, params=params)
                if resp.status_code in (429, 500, 502, 503, 504):
                    # Server-busy / rate-limited: back off and retry.
                    if attempt < retries:
                        time.sleep(_backoff_delay(attempt))
                        continue
                resp.raise_for_status()
                result = FetchResult(
                    url=str(resp.url),
                    status_code=resp.status_code,
                    content=resp.content,
                    content_type=resp.headers.get("content-type"),
                    http_version=getattr(resp, "http_version", None),
                )
                if use_cache:
                    self._write_cache(key, result)
                return result
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code == 404:
                    # Permanent miss: do not retry, do not cache.
                    raise
                if attempt < retries:
                    time.sleep(_backoff_delay(attempt))
                    continue
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt < retries:
                    time.sleep(_backoff_delay(attempt))
                    continue
            except Exception as exc:  # pragma: no cover - defensive
                last_exc = exc
                if attempt < retries:
                    time.sleep(_backoff_delay(attempt))
                    continue
        raise httpx.HTTPError(f"Failed to fetch {url} after {retries + 1} attempts: {last_exc!r}") from last_exc

    def get_json(self, url: str, **kwargs: Any) -> Any:
        result = self.get(url, **kwargs)
        return json.loads(result.text)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "Fetcher":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
