import asyncio
import json

import run
from helpdesk import HelpdeskError

DEC = {"action": "reply", "body": {"language": "nl", "category": "question", "priority": "P4", "confidence": 0.9},
       "faq_ids": ["F01"], "outcome": "posted", "tokens": {"input": 1, "output": 2},
       "verification": {"english_back_translation": "Your IBAN NL91ABNA0417164300 is fine"}}


def test_log_line_masks_and_has_no_body():
    line = json.loads(run.log_line("T001", DEC, "posted"))
    assert set(line) == {"ts", "id", "language", "category", "priority", "action", "confidence", "faq_ids",
                         "back_translation", "refusals", "outcome", "error", "tokens"}
    assert "[REDACTED]" in line["back_translation"] and "NL91" not in json.dumps(line)


class FakeHD:
    def open_tickets(self):
        yield from [{"id": "T001"}, {"id": "T002"}, {"id": "T003"}]


def go(monkeypatch, tmp_path, fake_decide):
    monkeypatch.setattr(run, "decide", fake_decide)
    log = tmp_path / "log.jsonl"
    counts = asyncio.run(run.run(FakeHD(), str(log)))
    return counts, [json.loads(l) for l in log.read_text().splitlines()]


def test_failed_ticket_does_not_stop_run(monkeypatch, tmp_path):
    async def fake(ticket, post):
        if ticket["id"] == "T001":
            raise HelpdeskError(503)
        return DEC
    counts, lines = go(monkeypatch, tmp_path, fake)
    assert [l["outcome"] for l in lines] == ["failed", "posted", "posted"]
    assert counts == {"failed": 1, "posted": 2}


class BrokenListHD:
    def open_tickets(self):
        yield {"id": "T001"}
        raise HelpdeskError(503)


def test_listing_failure_ends_run_cleanly(monkeypatch, tmp_path):
    async def fake(ticket, post):
        return DEC
    monkeypatch.setattr(run, "decide", fake)
    log = tmp_path / "log.jsonl"
    counts = asyncio.run(run.run(BrokenListHD(), str(log)))
    assert counts == {"posted": 1, "listing_failed": 1}
    assert len(log.read_text().splitlines()) == 1
