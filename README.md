# Roosterly support-ticket agent

## How to run
```bash
uv sync                                   # Python 3.12, google-adk, httpx
cp .env.example .env                      # fill HELPDESK_KEY, HELPDESK_EMAIL (and GEMINI_API_KEY if not exported)
uv run --env-file .env python run.py      # handle every open ticket once; one log line per ticket in logs/
uv run --env-file .env python eval.py <label>   # eval on the 10 labelled examples (posts nothing)
uv run pytest -q                          # 32 offline tests
```

## Decisions
1. **An ADK agent that acts through guarded tools.** One fresh `gemini-3.8-flash` session per ticket, whose only tools
   are `reply`, `handoff`, `close`. The client's rules live *in the tools*, not only in the prompt: the ticket id is bound
   in code (the model cannot touch another ticket), `reply` refuses unless it cites a real FAQ entry (F01–F12), no
   must-escalate topic is flagged (by the agent *and*, independently, by the verifier), confidence ≥ 0.7 and the
   verifier approves; after any refusal only `handoff` is allowed, so the model cannot retry around a rule; a second
   action is refused; if the agent ends without deciding, code posts a handoff. Ticket text is wrapped in `<ticket>` and declared data. Per-ticket
   sessions keep one hostile ticket from steering others.
2. **Dutch: work in Dutch directly, check in English.** The agent reads and answers in the customer's language (keeps
   the FAQ's Dutch menu names exact; no translate-and-back drift). Every draft goes through a second call that
   back-translates it to English and checks every claim against the cited FAQ entries and the language. The English
   back-translation is logged, so someone who reads no Dutch can review each reply. It costs one extra call per reply.
3. **Unsure = handoff.** I count the agent unsure when confidence < 0.7, no FAQ entry answers it, any refund /
   cancellation / contract / GDPR (AVG) / security / legal / churn topic is present, or the verifier rejects the draft.
   Handing off is never punished; a wrong reply reaches a customer.

*Assumptions:* a GDPR data request is a human task even if routine; a plan upgrade counts as a contract change (so a
human handles it); spam/empty is the only reason to close; priority is judged on impact (see Eval). *Final run:* 30/30
handled, 0 failed — 11 replies, 17 handoffs, 2 closes (`logs/run-20261118T161016Z.jsonl`). *AI tools:* built with Claude Code — brainstorm → written design → plan → test-first
implementation, a separate reviewer agent on the final code. Every line was read and the eval was run by me.

## Reliability
- **429**: wait `Retry-After`, retry. Calls are spaced ≥ 0.25 s (4/s) so it rarely happens.
- **503**: retry after 0.5, 1, 2, 4, 8 s (nothing was saved). Network errors are retried the same way for GETs; a
  POST is never resent blindly — the code asks the server whether it was saved. If the helpdesk stays down, that
  ticket is logged `failed`, stays open, and the next run picks it up.
- **409**: means "already answered" → logged `already_handled`, never retried.
- **Crash / re-run**: the helpdesk is the source of truth (no local state file to go stale). A run only lists open
  tickets, and before every POST it checks `GET /tickets/{id}` → `handled`. Tested by hard-killing `run.py` twice
  mid-run (it resumed at the next ticket) and by two runs racing each other: nothing was ever answered twice.
- **Security**: keys only from env (`.env` is git-ignored); IBANs and card numbers are masked in replies, notes and the
  whole log line; ticket bodies are never logged.

## Eval and fix
`eval.py` runs the real agent on `GET /examples`, records actions instead of posting, scores against Nordavo's labels,
and has a *different* model (`gemini-3.5-flash`) judge reply quality. Results in `eval/results-*.json`.

| run | action | category | priority | language | unsafe replies | replies good | $ / 100 tickets |
|---|---|---|---|---|---|---|---|
| baseline | 10 | 8 | 9 | 10 | 0 | 6/6 | 1.11 |
| fix step 1: category = topic | 10 | **10** | 7 | 10 | 0 | 6/6 | 1.16 |
| fix step 2: + priority by impact | 10 | 10 | **9** | 10 | 0 | 6/6 | 1.13 |
| thinking medium/low | 10 | 10 | 9 | 10 | 0 | 6/6 | 0.78 |
| final: + review fixes | 10 | 10 | 9 | 10 | 0 | 6/6 | **0.83** |

**The fix.** The agent called answerable tickets `question` even when they were about a crash or a price. Adding
"category is what the ticket is about" fixed category but broke priority: billing became "money involved → P2". One more
line ("priority by impact; a price question is P4") fixed both. Remaining miss: a GDPR request rated P1 instead of P2
(still handed off). Then I lowered thinking: `low` for the agent made it invent facts (the verifier caught them; two
replies became handoffs), so the agent uses `medium`, the verifier `low`.
**Cost** (final eval, gemini-3.8-flash at $0.75 in / $3.75 out per 1M tokens, verifier included, judge excluded):
62,551 input + 9,598 output tokens for 10 tickets → (62,551 × 0.75 + 9,598 × 3.75) / 1M = $0.083 → **$0.83 per 100**.

## What I would improve
- **Next step:** a bigger labelled set (and several eval runs per change). Ten examples cannot separate a real fix from
  noise; I would also add a cheap keyword backstop (e.g. "terugbetaling", "opzeggen", "AVG") in code for must-escalate
  topics, so safety does not rest on the model flagging them.
- **Change in the brief:** P2's "money or the contract is involved" reads as covering any price question. I would define
  it as "a payment problem, disputed charge or contract change", which is what the labels mean.
