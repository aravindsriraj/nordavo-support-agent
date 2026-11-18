"""Roosterly helpdesk client: auth, rate limit, retries, and the never-answer-twice guard."""
import json
import os
import time

import httpx

BACKOFF = [0.5, 1, 2, 4, 8]  # waits between retries for 503 / network errors


class HelpdeskError(Exception):
    def __init__(self, status: int, body: dict | None = None):
        super().__init__(f"helpdesk {status}: {body}")
        self.status = status
        self.body = body or {}


class AlreadyHandled(HelpdeskError):
    """409: the ticket already got a decision. Never retried."""


class Helpdesk:
    def __init__(self, base_url: str, key: str, email: str, *, min_interval: float = 0.25,
                 sleep=time.sleep, transport=None):
        self.min_interval = min_interval  # 4 calls/s, under the 5/s limit
        self.sleep = sleep
        self._last = 0.0
        self.client = httpx.Client(
            base_url=base_url.rstrip("/"), transport=transport, timeout=30,
            headers={"Authorization": f"Bearer {key}", "X-Candidate-Email": email})

    @classmethod
    def from_env(cls) -> "Helpdesk":
        return cls(os.environ["HELPDESK_URL"], os.environ["HELPDESK_KEY"], os.environ["HELPDESK_EMAIL"])

    def _throttle(self):
        wait = self._last + self.min_interval - time.monotonic()
        if wait > 0:
            self.sleep(wait)
        self._last = time.monotonic()

    def request(self, method: str, path: str, json: dict | None = None, params: dict | None = None) -> dict:
        backoff = list(BACKOFF)
        while True:
            self._throttle()
            try:
                r = self.client.request(method, path, json=json, params=params)
            except httpx.TransportError:
                # Unknown whether a POST was saved; a retry then gets 409, which post_once treats as done.
                if not backoff:
                    raise HelpdeskError(0, {"error": "network"})
                self.sleep(backoff.pop(0))
                continue
            if r.status_code == 429:
                self.sleep(float(r.headers.get("Retry-After", 1)))
                continue
            if r.status_code == 503:
                if not backoff:
                    raise HelpdeskError(503, _json(r))
                self.sleep(backoff.pop(0))
                continue
            if r.status_code == 409:
                raise AlreadyHandled(409, _json(r))
            if r.status_code >= 400:
                raise HelpdeskError(r.status_code, _json(r))
            return _json(r)

    def open_tickets(self):
        cursor = None
        while True:
            params = {"status": "open", "limit": 10}
            if cursor:
                params["cursor"] = cursor
            page = self.request("GET", "/tickets", params=params)
            yield from page["tickets"]
            cursor = page.get("next_cursor")
            if not cursor:
                return

    def get_ticket(self, id: str) -> dict:
        return self.request("GET", f"/tickets/{id}")

    def post_action(self, id: str, action: str, body: dict) -> dict:
        return self.request("POST", f"/tickets/{id}/{action}", json=body)

    def examples(self) -> list[dict]:
        return self.request("GET", "/examples")["examples"]

    def reset(self) -> dict:
        return self.request("POST", "/practice/reset")


class State:
    """Local record of tickets we already answered. Survives crashes (atomic write)."""

    def __init__(self, path: str = "state.json"):
        self.path = path
        self.data = json.load(open(path)) if os.path.exists(path) else {}

    def done(self, id: str) -> bool:
        return id in self.data

    def mark(self, id: str, outcome: str) -> None:
        self.data[id] = outcome
        with open(self.path + ".tmp", "w") as f:
            json.dump(self.data, f, indent=1)
        os.replace(self.path + ".tmp", self.path)


def post_once(hd: Helpdesk, state: State, ticket_id: str, action: str, body: dict) -> str:
    """Post a decision unless this ticket was already answered. Returns 'posted' or 'already_handled'."""
    if state.done(ticket_id):
        return "already_handled"
    if is_handled(hd.get_ticket(ticket_id)):  # covers a crash between POST and state write
        state.mark(ticket_id, "already_handled")
        return "already_handled"
    try:
        hd.post_action(ticket_id, action, body)
    except AlreadyHandled:
        state.mark(ticket_id, "already_handled")
        return "already_handled"
    state.mark(ticket_id, "posted")
    return "posted"


def _json(r: httpx.Response) -> dict:
    try:
        return r.json()
    except ValueError:
        return {}


def is_handled(ticket: dict) -> bool:
    # TODO(verify live): field name for "already handled"
    return ticket.get("status", "open") != "open"
