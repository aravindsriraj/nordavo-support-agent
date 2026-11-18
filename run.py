"""One command: handle every open helpdesk ticket once.  uv run --env-file .env python run.py"""
import asyncio
import json
import os
from collections import Counter
from datetime import datetime, timezone
from functools import partial

from agent import decide, mask_payment
from helpdesk import Helpdesk, post_once


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
        for ticket in hd.open_tickets():
            tid = ticket["id"]
            try:
                d = await decide(ticket, partial(post_once, hd, tid))
                outcome = "fallback_handoff" if d.get("fallback") and d["outcome"] == "posted" else d["outcome"]
                line = log_line(tid, d, outcome)
            except Exception as e:  # one bad ticket never stops the run; next run picks it up
                outcome = "failed"
                line = log_line(tid, None, outcome, f"{type(e).__name__}: {e}")
            counts[outcome] += 1
            log.write(line + "\n")
            log.flush()
            print(line)
    return dict(counts)


def main():
    os.makedirs("logs", exist_ok=True)
    path = f"logs/run-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.jsonl"
    counts = asyncio.run(run(Helpdesk.from_env(), path))
    print(f"done: {counts} -> {path}")


if __name__ == "__main__":
    main()
