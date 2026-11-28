# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslamsynth.fetch: cache, throttle, Retry-After, bounded retries (network mocked)."""
import json
import socket

import pytest

from haslamsynth import fetch, jlc


class Clock:
    def __init__(self):
        self.t = 1000.0
        self.slept = []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(round(s, 3))
        self.t += s


def mk(tmp_path, answers):
    clk = Clock()
    c = fetch.Client(root=tmp_path, sleep=clk.sleep, clock=clk)
    calls = []

    def transport(method, url, headers, body, timeout):
        calls.append((method, url, headers, body))
        a = answers.pop(0)
        if isinstance(a, BaseException):
            raise a
        return a
    c.transport = transport
    return c, clk, calls


def test_cache_hit_needs_no_request_and_user_agent_is_generic(tmp_path):
    c, clk, calls = mk(tmp_path, [(200, {"content-type": "application/pdf"}, b"%PDF-1.4 x")])
    r1 = c.get("https://www.ti.com/lit/ds/symlink/tps709.pdf")
    r2 = c.get("https://www.ti.com/lit/ds/symlink/tps709.pdf")
    assert r1.body == r2.body and r2.from_cache and len(calls) == 1
    ua = calls[0][2]["User-Agent"]
    assert "haslamsynth" in ua and "@" not in ua


def test_max_age_expires_entry(tmp_path):
    c, clk, calls = mk(tmp_path, [(200, {}, b"a"), (200, {}, b"b")])
    c.get("https://h.example/x", max_age=10)
    clk.t += 11
    assert c.get("https://h.example/x", max_age=10).body == b"b" and len(calls) == 2


def test_throttle_spaces_requests_per_host(tmp_path):
    c, clk, calls = mk(tmp_path, [(200, {}, b"1"), (200, {}, b"2"), (200, {}, b"3")])
    c.get("https://a.example/1")
    c.get("https://a.example/2")             # same host, no time passed: waits 1 s
    c.get("https://b.example/1")             # other host: no wait
    assert clk.slept == [1.0]


def test_retry_after_honoured_then_success(tmp_path):
    c, clk, calls = mk(tmp_path, [(429, {"retry-after": "7"}, b""), (200, {}, b"ok")])
    assert c.get("https://a.example/x").body == b"ok"
    assert 7.0 in clk.slept and len(calls) == 2


def test_at_most_three_tries_with_backoff(tmp_path):
    c, clk, calls = mk(tmp_path, [(503, {}, b"")] * 3 + [(200, {}, b"never")])
    with pytest.raises(fetch.FetchError) as e:
        c.get("https://a.example/x")
    assert e.value.status == 503 and len(calls) == 3
    assert [s for s in clk.slept if s >= 2] == [2.0, 4.0]


def test_long_retry_after_gives_up_without_sleeping(tmp_path):
    c, clk, calls = mk(tmp_path, [(429, {"retry-after": "3600"}, b"")])
    with pytest.raises(fetch.FetchError, match="wait 3600"):
        c.get("https://a.example/x")
    assert len(calls) == 1 and max(clk.slept or [0]) < 2


def test_403_not_retried_and_remembered(tmp_path):
    c, clk, calls = mk(tmp_path, [(403, {}, b"denied")])
    url = "https://www.lcsc.com/datasheet/x.pdf"
    with pytest.raises(fetch.FetchError, match="403"):
        c.get(url)
    with pytest.raises(fetch.FetchError, match="remembered"):
        c.get(url)
    assert len(calls) == 1


def test_timeout_marks_host_dead_for_the_run(tmp_path):
    c, clk, calls = mk(tmp_path, [socket.timeout("read")])
    with pytest.raises(fetch.FetchError, match="timed out"):
        c.get("https://www.st.com/a.pdf")
    with pytest.raises(fetch.FetchError, match="not asked again"):
        c.get("https://www.st.com/b.pdf")
    assert len(calls) == 1


def test_retry_after_http_date():
    assert fetch.retry_after("Wed, 21 Oct 2015 07:28:00 GMT", now=1445412480 - 10) == pytest.approx(10)
    assert fetch.retry_after("bogus") is None and fetch.retry_after("5") == 5


def test_jlc_search_uses_client_and_caches(tmp_path):
    body = json.dumps({"code": 200, "data": {"componentPageInfo": {"list": [{"componentCode": "C1"}]}}}).encode()
    c, clk, calls = mk(tmp_path, [(200, {}, body)])
    assert jlc.search("100nF 0603", client=c)[0]["componentCode"] == "C1"
    assert jlc.search("100nF 0603", client=c)[0]["componentCode"] == "C1"
    assert len(calls) == 1 and calls[0][0] == "POST"


def test_jlc_error_body_not_cached(tmp_path):
    bad = json.dumps({"code": 500, "message": "busy"}).encode()
    good = json.dumps({"code": 200, "data": {"componentPageInfo": {"list": []}}}).encode()
    c, clk, calls = mk(tmp_path, [(200, {}, bad), (200, {}, good)])
    with pytest.raises(fetch.FetchError, match="busy"):
        jlc.search("x", client=c)
    assert jlc.search("x", client=c) == [] and len(calls) == 2
