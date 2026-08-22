"""Tiny disk-backed HTTP cache shared by the online resolvers.

Audits get re-run constantly while a workflow is being fixed, and the upstream
APIs are rate limited, so every response is cached on disk and reused.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

DEFAULT_TTL = 7 * 24 * 3600  # a week; licences do not change hourly
USER_AGENT = "comfyaudit/0.1 (+https://github.com/dughogan/comfyaudit)"


def cache_dir() -> str:
    base = os.environ.get("COMFYAUDIT_CACHE") or os.path.join(
        os.path.expanduser("~"), ".cache", "comfyaudit"
    )
    os.makedirs(base, exist_ok=True)
    return base


class HttpCache:
    """GET JSON with an on-disk cache and graceful failure.

    Network problems never raise: a resolver that cannot reach the internet
    should degrade to the bundled knowledge base, not abort the audit.
    """

    def __init__(self, ttl: int = DEFAULT_TTL, timeout: float = 12.0,
                 offline: bool = False) -> None:
        self.ttl = ttl
        self.timeout = timeout
        self.offline = offline
        self.hits = 0
        self.misses = 0
        self.errors: list[str] = []

    def get_json(self, url: str, headers: dict[str, str] | None = None) -> Any | None:
        path = self._path(url)
        cached = self._read(path)
        if cached is not None:
            self.hits += 1
            return cached
        if self.offline:
            return None

        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403, 404):
                # A definitive "no" is worth caching so we stop asking.
                self._write(path, {"__error__": exc.code})
            self.errors.append(f"{url} -> HTTP {exc.code}")
            self.misses += 1
            return None
        except Exception as exc:  # noqa: BLE001 - network, DNS, TLS, JSON, ...
            self.errors.append(f"{url} -> {type(exc).__name__}: {exc}")
            self.misses += 1
            return None

        self._write(path, payload)
        self.misses += 1
        return payload

    # -- internals ---------------------------------------------------------

    def _path(self, url: str) -> str:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
        return os.path.join(cache_dir(), f"{digest}.json")

    def _read(self, path: str) -> Any | None:
        try:
            stat = os.stat(path)
        except OSError:
            return None
        if not self.offline and time.time() - stat.st_mtime > self.ttl:
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return None
        if isinstance(payload, dict) and "__error__" in payload:
            return None
        return payload

    def _write(self, path: str, payload: Any) -> None:
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
        except OSError:
            pass
