import httpx
import pytest

from helpdesk import AlreadyHandled, Helpdesk, HelpdeskError


def make(responses, sleeps):
    """responses: list of httpx.Response or Exception, consumed in order."""
    calls = []

    def handler(request):
        calls.append(request)
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    hd = Helpdesk("https://h.test", "k", "e@x", sleep=sleeps.append,
                  transport=httpx.MockTransport(handler))
    return hd, calls


def backoffs(sleeps):
    # rate-limit sleeps are <= 0.25; backoff sleeps are >= 0.5
    return [s for s in sleeps if s >= 0.5]


def test_sends_auth_and_email_headers():
    hd, calls = make([httpx.Response(200, json={"ok": 1})], [])
    assert hd.request("GET", "/status") == {"ok": 1}
    assert calls[0].headers["Authorization"] == "Bearer k"
    assert calls[0].headers["X-Candidate-Email"] == "e@x"


def test_retries_503_then_succeeds():
    sleeps = []
    hd, calls = make([httpx.Response(503), httpx.Response(503), httpx.Response(200, json={"a": 1})], sleeps)
    assert hd.request("GET", "/status") == {"a": 1}
    assert backoffs(sleeps) == [0.5, 1]


def test_503_gives_up_after_5_retries():
    sleeps = []
    hd, calls = make([httpx.Response(503) for _ in range(6)], sleeps)
    with pytest.raises(HelpdeskError) as e:
        hd.request("GET", "/status")
    assert e.value.status == 503
    assert len(calls) == 6


def test_429_waits_retry_after():
    sleeps = []
    hd, _ = make([httpx.Response(429, headers={"Retry-After": "2"}), httpx.Response(200, json={})], sleeps)
    hd.request("GET", "/status")
    assert 2 in sleeps


def test_409_raises_already_handled_without_retry():
    hd, calls = make([httpx.Response(409, json={"error": "already_handled"})], [])
    with pytest.raises(AlreadyHandled):
        hd.post_action("T001", "reply", {})
    assert len(calls) == 1


def test_transport_error_is_retried():
    hd, calls = make([httpx.ConnectError("boom"), httpx.Response(200, json={"x": 1})], [])
    assert hd.request("GET", "/status") == {"x": 1}


def test_open_tickets_follows_cursor():
    hd, calls = make([
        httpx.Response(200, json={"tickets": [{"id": "T001"}], "next_cursor": "T010"}),
        httpx.Response(200, json={"tickets": [{"id": "T011"}], "next_cursor": None}),
    ], [])
    assert [t["id"] for t in hd.open_tickets()] == ["T001", "T011"]
    assert calls[1].url.params["cursor"] == "T010"
    assert calls[0].url.params["status"] == "open"


def test_min_interval_between_calls():
    sleeps = []
    hd, _ = make([httpx.Response(200, json={}), httpx.Response(200, json={})], sleeps)
    hd.request("GET", "/status")
    hd.request("GET", "/status")
    assert any(0.2 < s <= 0.25 for s in sleeps)
