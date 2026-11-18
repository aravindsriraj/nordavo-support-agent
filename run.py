"""One command: handle every open helpdesk ticket once.  uv run --env-file .env python run.py"""
import asyncio
import json
import os
from collections import Counter
from datetime import datetime, timezone
from functools import partial

from agent import decide, mask_payment
from helpdesk import Helpdesk, HelpdeskError, post_once


def log_line(ticket_id: str, decision: dict | None, outcome: str, error: str | None = None) -> str:
    d = decision or {}
    b = d.get("body", {})
    line = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "id": ticket_id,
        "language": b.get("language"), "category": b.get("category"), "priority": b.get("priority"),
        "action": d.get("action"), "confidence": b.get("confidence"), "faq_ids": d.get("faq_ids"),
        "back_translation": (d.get("verification") or {}).get("english_back_translation"),
        "refusals": d.get("refusals"), "outcome": outcome, "error": error or d.get("error"), "tokens": d.get("tokens"),
    }
    # The whole line goes through the mask: no payment details in logs, ever. No ticket body is logged.
    return mask_payment(json.dumps(line, ensure_ascii=False))


async def run(hd, log_path: str) -> dict[str, int]:
    counts = Counter()
    with open(log_path, "a") as log:
        try:
            await _handle_all(hd, log, counts)
        except HelpdeskError as e:  # listing tickets failed: stop cleanly; unhandled tickets stay open for a re-run
            counts["listing_failed"] += 1
            print(f"could not list tickets ({e}); re-run to continue")
    return dict(counts)


async def _handle_all(hd, log, counts: Counter) -> None:
    for ticket in hd.open_tickets():
        tid = ticket["id"]
        try:
            d = await decide(ticket, partial(post_once, hd, tid))
            outcome = "fallback_handoff" if d.get("fallback") and d["outcome"] == "posted" else d["outcome"]
            line = log_line(tid, d, outcome)
        except Exception as e:  # one bad ticket never stops the run; it stays open and the next run picks it up
            outcome = "failed"
            line = log_line(tid, None, outcome, f"{type(e).__name__}: {e}")
        counts[outcome] += 1
        log.write(line + "\n")
        log.flush()
        print(line)


def main():
    os.makedirs("logs", exist_ok=True)
    path = f"logs/run-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.jsonl"
    counts = asyncio.run(run(Helpdesk.from_env(), path))
    print(f"done: {counts} -> {path}")


if __name__ == "__main__":
    main()
