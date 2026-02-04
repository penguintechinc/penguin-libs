"""HTTP/3-preferred async client with automatic HTTP/2 fallback.

Uses httpx with aioquic transport for HTTP/3 connections.
Falls back to standard httpx HTTP/2 when HTTP/3 is unavailable.

Status: EXPERIMENTAL. The aioquic httpx transport is alpha-quality.
HTTP/2 fallback is production-ready via standard httpx.
"""

from __future__ import annotations

import asyncio
import logging
import time
from types import TracebackType
from typing import Any

import httpx

from .config import ClientConfig
from .exceptions import H3ClientError
from .protocol import Protocol
from .retry import async_retry

logger = logging.getLogger(__name__)


class H3Client:
    """Async HTTP client that prefers HTTP/3 with HTTP/2 fallback.

    Usage::

        async with H3Client(config) as client:
            response = await client.get("/api/v1/data")
            data = response.json()
    """

    def __init__(self, cfg: ClientConfig | None = None) -> None:
        self._cfg = cfg or ClientConfig()
        self._h2_client: httpx.AsyncClient | None = None
        self._h3_client: httpx.AsyncClient | None = None
        self._use_h3 = self._cfg.h3_enabled
        self._last_h3_try: float = 0.0
        self._lock = asyncio.Lock()

    async def _ensure_clients(self) -> None:
        """Lazily initialise HTTP clients."""
        if self._h2_client is None:
            self._h2_client = httpx.AsyncClient(
                base_url=self._cfg.base_url,
                http2=True,
                timeout=self._cfg.request_timeout,
                verify=self._cfg.verify_ssl,
                headers=self._cfg.headers,
            )

        if self._h3_client is None and self._cfg.h3_enabled:
            try:
                from httpx_h3 import AsyncH3Client as _H3  # type: ignore[import-untyped]

                self._h3_client = _H3(
                    base_url=self._cfg.base_url,
                    timeout=self._cfg.request_timeout,
                    verify=self._cfg.verify_ssl,
                    headers=self._cfg.headers,
                )
            except ImportError:
                logger.warning(
                    "httpx_h3 not available, HTTP/3 client disabled. "
                    "Install with: pip install httpx-h3"
                )
                self._use_h3 = False

    @property
    def protocol(self) -> Protocol:
        """Return the currently active protocol."""
        return Protocol.H3 if self._use_h3 else Protocol.H2

    async def _mark_h3_failed(self) -> None:
        """Record HTTP/3 failure and switch to HTTP/2."""
        async with self._lock:
            if self._use_h3:
                logger.warning("HTTP/3 failed, falling back to HTTP/2")
                self._use_h3 = False
                self._last_h3_try = time.monotonic()

    async def _maybe_retry_h3(self) -> None:
        """Re-attempt HTTP/3 if enough time has passed since last failure."""
        if not self._cfg.h3_enabled or self._h3_client is None:
            return
        async with self._lock:
            if (
                not self._use_h3
                and time.monotonic() - self._last_h3_try
                >= self._cfg.h3_retry_interval
            ):
                logger.info("Re-attempting HTTP/3")
                self._use_h3 = True

    def _active_client(self) -> httpx.AsyncClient:
        """Return the currently preferred client."""
        if self._use_h3 and self._h3_client is not None:
            return self._h3_client
        if self._h2_client is None:
            raise H3ClientError(
                "Client not initialized. Use 'async with H3Client()' context."
            )
        return self._h2_client

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Send an HTTP request with protocol fallback.

        Tries HTTP/3 first (if enabled), falls back to HTTP/2 on failure.
        """
        await self._ensure_clients()
        await self._maybe_retry_h3()

        if self._use_h3 and self._h3_client is not None:
            try:
                return await self._h3_client.request(method, url, **kwargs)
            except Exception as exc:
                logger.warning("HTTP/3 request failed: %s", exc)
                await self._mark_h3_failed()

        # Fallback to HTTP/2
        if self._h2_client is None:
            raise H3ClientError("No HTTP client available")
        return await self._h2_client.request(method, url, **kwargs)

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        """Send a GET request."""
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        """Send a POST request."""
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> httpx.Response:
        """Send a PUT request."""
        return await self.request("PUT", url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        """Send a DELETE request."""
        return await self.request("DELETE", url, **kwargs)

    async def close(self) -> None:
        """Close all underlying HTTP clients."""
        if self._h2_client is not None:
            await self._h2_client.aclose()
            self._h2_client = None
        if self._h3_client is not None:
            await self._h3_client.aclose()
            self._h3_client = None

    async def __aenter__(self) -> H3Client:
        await self._ensure_clients()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()
