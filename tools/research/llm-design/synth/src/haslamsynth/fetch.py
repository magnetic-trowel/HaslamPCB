# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""One gentle HTTP client for every haslamsynth command that fetches (`jlc`, `parts search`, `datasheet`,
`fp-fetch`); FRICTION #28 (obd-solar run: bursts of searches and retry loops against hosts that had said 429).

Rules, in the order a request meets them:

1. Cache: every successful response is stored under `~/.cache/haslamsynth/http/` (`HASLAMSYNTH_CACHE`
   moves the root), keyed by sha256(method, URL, body). A hit is returned without touching the network,
   unless it is older than the caller's `max_age` (seconds; None = keep for ever).
2. Refusals are remembered too (`<key>.fail.json`, kept FAIL_TTL seconds): a host that answered 403/404 or
   timed out is not asked the same thing again by the next command; `refresh=True` asks anyway.
   Within one process, a host that timed out or refused the connection is not contacted again at all.
3. Throttle: at least MIN_INTERVAL seconds between requests to one host, across processes (a stamp file per
   host under the cache root).
4. Retries: at most TRIES attempts in all, only for 429/500/502/503/504 and dropped connections; the wait is
   the server's `Retry-After` (seconds or HTTP date) or 2, 4 s; a `Retry-After` above MAX_WAIT ends the
   attempt instead of sleeping. 403/404/other statuses and timeouts are not retried.

The User-Agent names the tool, no personal data. Failures raise FetchError with the URL, the status and why.
"""
from __future__ import annotations

import email.utils
import hashlib
import json
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__

USER_AGENT = f"Mozilla/5.0 (compatible; haslamsynth/{__version__}; KiCad design tool)"
MIN_INTERVAL = 1.0
TRIES = 3
MAX_WAIT = 120.0
FAIL_TTL = 6 * 3600
RETRY_STATUS = {429, 500, 502, 503, 504}


def cache_root():
    return Path(os.environ.get("HASLAMSYNTH_CACHE") or Path.home() / ".cache" / "haslamsynth")


class FetchError(RuntimeError):
    def __init__(self, url, status=None, reason="", cached=False):
        self.url, self.status, self.reason, self.cached = url, status, reason, cached
        s = f"HTTP {status}" if status else "no response"
        super().__init__(f"{url}: {s} ({reason})" + (" [remembered from an earlier try; --refresh asks again]"
                                                      if cached else ""))


@dataclass
class Response:
    url: str
    status: int
    headers: dict
    body: bytes
    from_cache: bool = False
    fetched_at: float = field(default_factory=time.time)

    def json(self):
        return json.loads(self.body.decode("utf-8"))

    @property
    def content_type(self):
        return (self.headers.get("content-type") or "").split(";")[0].strip().lower()


def _urllib_transport(method, url, headers, body, timeout):
    """(status, headers, body); raises urllib/socket errors. Tests replace Client.transport."""
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:      # noqa: S310 - http(s) only, checked below
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, e.read() or b""


def retry_after(value, now=None):
    """Seconds to wait from a Retry-After header (delta-seconds or HTTP date); None if absent or unreadable."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        t = email.utils.parsedate_to_datetime(value).timestamp()
    except (TypeError, ValueError):
        return None
    return max(0.0, t - (time.time() if now is None else now))


class Client:
    def __init__(self, root=None, min_interval=MIN_INTERVAL, tries=TRIES, timeout=30, sleep=time.sleep,
                 clock=time.time, log=None):
        self.root = Path(root) if root else cache_root()
        self.dir = self.root / "http"
        self.min_interval, self.tries, self.timeout = min_interval, tries, timeout
        self.sleep, self.clock = sleep, clock
        self.log = log or (lambda msg: None)
        self.transport = _urllib_transport
        self.dead_hosts = {}          # host -> reason, this process only
        self.requests = 0             # network requests actually sent

    # -- cache ---------------------------------------------------------------------------------------
    def key(self, method, url, body=None):
        h = hashlib.sha256(f"{method} {url}\n".encode() + (body or b"")).hexdigest()
        return h[:2], h

    def _paths(self, method, url, body):
        sub, h = self.key(method, url, body)
        d = self.dir / sub
        return d / f"{h}.body", d / f"{h}.json", d / f"{h}.fail.json"

    def cached(self, method, url, body=None, max_age=None):
        bp, mp, _ = self._paths(method, url, body)
        if not (bp.exists() and mp.exists()):
            return None
        meta = json.loads(mp.read_text())
        if max_age is not None and self.clock() - meta.get("fetched_at", 0) > max_age:
            return None
        return Response(url, meta["status"], meta.get("headers", {}), bp.read_bytes(), True, meta.get("fetched_at", 0))

    def _store(self, method, url, body, resp):
        bp, mp, fp = self._paths(method, url, body)
        bp.parent.mkdir(parents=True, exist_ok=True)
        bp.write_bytes(resp.body)
        keep = {k: v for k, v in resp.headers.items() if k in ("content-type", "content-disposition", "last-modified")}
        mp.write_text(json.dumps(dict(url=url, method=method, status=resp.status, headers=keep,
                                      fetched_at=resp.fetched_at), indent=1))
        fp.unlink(missing_ok=True)

    def forget(self, method, url, body=None):
        """Drop a cached answer (e.g. a 200 whose body says the call failed)."""
        for p in self._paths(method, url, body):
            p.unlink(missing_ok=True)

    def _remember_failure(self, method, url, body, err):
        _, _, fp = self._paths(method, url, body)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(json.dumps(dict(url=url, status=err.status, reason=err.reason, at=self.clock())))

    def _remembered_failure(self, method, url, body):
        _, _, fp = self._paths(method, url, body)
        if not fp.exists():
            return None
        f = json.loads(fp.read_text())
        if self.clock() - f.get("at", 0) > FAIL_TTL:
            return None
        return FetchError(url, f.get("status"), f.get("reason", ""), cached=True)

    # -- throttle ------------------------------------------------------------------------------------
    def _throttle(self, host):
        stamp = self.root / "throttle" / host
        stamp.parent.mkdir(parents=True, exist_ok=True)
        if stamp.exists():
            try:
                last = float(stamp.read_text() or 0)
            except ValueError:
                last = 0.0
            wait = last + self.min_interval - self.clock()
            if wait > 0:
                self.sleep(wait)
        stamp.write_text(repr(self.clock()))

    # -- requests ------------------------------------------------------------------------------------
    def request(self, method, url, body=None, headers=None, max_age=None, cache=True, refresh=False, timeout=None):
        u = urllib.parse.urlsplit(url)
        if u.scheme not in ("http", "https") or not u.hostname:
            raise FetchError(url, None, "only http(s) URLs")
        host = u.hostname.lower()
        if cache and not refresh:
            hit = self.cached(method, url, body, max_age)
            if hit is not None:
                return hit
            prev = self._remembered_failure(method, url, body)
            if prev is not None:
                raise prev
        if host in self.dead_hosts:
            raise FetchError(url, None, f"{host} already failed in this run: {self.dead_hosts[host]}; not asked again")
        hdrs = {"User-Agent": USER_AGENT, "Accept": "*/*", **(headers or {})}
        err = None
        for attempt in range(self.tries):
            self._throttle(host)
            self.requests += 1
            self.log(f"  GET {url}" if method == "GET" else f"  {method} {url}")
            try:
                status, rh, data = self.transport(method, url, hdrs, body, timeout or self.timeout)
            except (socket.timeout, TimeoutError) as e:
                err = FetchError(url, None, f"timed out after {timeout or self.timeout:g} s ({e}); a stalled host "
                                            "is not retried")
                self.dead_hosts[host] = "timed out"
                break
            except (urllib.error.URLError, ConnectionError, OSError) as e:
                reason = getattr(e, "reason", e)
                if isinstance(reason, (socket.timeout, TimeoutError)):
                    err = FetchError(url, None, f"timed out ({reason}); a stalled host is not retried")
                    self.dead_hosts[host] = "timed out"
                    break
                err = FetchError(url, None, f"connection failed: {reason}")
                if isinstance(reason, (ConnectionRefusedError, socket.gaierror)):
                    self.dead_hosts[host] = str(reason)
                    break
                wait = 2.0 * 2 ** attempt
            else:
                if 200 <= status < 300:
                    resp = Response(url, status, rh, data, False, self.clock())
                    if cache:
                        self._store(method, url, body, resp)
                    return resp
                err = FetchError(url, status, _status_reason(status, rh, data))
                if status not in RETRY_STATUS:
                    break
                ra = retry_after(rh.get("retry-after"), self.clock())
                if ra is not None and ra > MAX_WAIT:
                    err = FetchError(url, status, f"server asks to wait {ra:.0f} s (> {MAX_WAIT:.0f} s); try later")
                    break
                wait = max(ra or 0.0, 2.0 * 2 ** attempt)
            if attempt + 1 < self.tries:
                self.log(f"  {err}; waiting {wait:.0f} s (try {attempt + 2} of {self.tries})")
                self.sleep(wait)
        if cache and (err.status in (403, 404, 410, 451) or (err.status is None and "timed out" in err.reason)):
            self._remember_failure(method, url, body, err)
        raise err

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    @staticmethod
    def json_body(payload):
        return json.dumps(payload, sort_keys=True).encode()

    def post_json(self, url, payload, headers=None, **kw):
        body = self.json_body(payload)
        return self.request("POST", url, body=body,
                            headers={"Content-Type": "application/json", "Accept": "application/json",
                                     **(headers or {})}, **kw)


def _status_reason(status, headers, data):
    if status == 403:
        return "forbidden: this host refuses this client (seen for LCSC datasheet URLs from cloud hosts)"
    if status == 404:
        return "not found"
    if status == 429:
        return "rate limited"
    txt = data[:120].decode("utf-8", "replace").strip().replace("\n", " ")
    return txt or "error"


_default = None


def client(log=None):
    """The process-wide client (one throttle and dead-host list per process)."""
    global _default
    if _default is None:
        _default = Client(log=log)
    elif log is not None:
        _default.log = log
    return _default
