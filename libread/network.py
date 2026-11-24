"""HTTP layer: shared session, polite headers, retries and streaming downloads."""

from __future__ import annotations

import time
from typing import Callable, Optional

import requests

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://libread.com/",
}


class HttpClient:
    """A requests wrapper with automatic retries and streamed binary downloads."""

    def __init__(
        self,
        timeout: float = 30.0,
        retries: int = 3,
        backoff: float = 1.5,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def _request(self, method: str, url: str, stream: bool = False, **kwargs):
        kwargs.setdefault("timeout", self.timeout)
        last_error: Optional[requests.RequestException] = None
        for attempt in range(1, self.retries + 1):
            try:
                response = self.session.request(method, url, stream=stream, **kwargs)
                if response.status_code >= 400:
                    response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
                print(f"  ! {url} failed (attempt {attempt}/{self.retries}): {exc}")
                if attempt < self.retries:
                    time.sleep(self.backoff * attempt)
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"unreachable for {url}")

    def get_text(self, url: str, **kwargs) -> str:
        return self._request("GET", url, **kwargs).text

    def download(
        self,
        url: str,
        destination: str,
        progress: Optional[Callable[[int, int], None]] = None,
    ) -> int:
        """Stream a file to disk in chunks. Returns bytes written."""
        response = self._request("GET", url, stream=True)
        total = int(response.headers.get("Content-Length") or 0)
        written = 0
        with open(destination, "wb") as handle:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if chunk:
                    handle.write(chunk)
                    written += len(chunk)
                    if progress is not None:
                        progress(written, total)
        return written
