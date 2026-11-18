"""The triage agent: guarded action tools (client rules enforced in code), verifier, and per-ticket run."""
import re
from pathlib import Path
from typing import Callable

LANGUAGES = {"nl", "en", "de"}
CATEGORIES = {"bug", "billing", "feature_request", "question", "other"}
PRIORITIES = {"P1", "P2", "P3", "P4"}
# Client rule: these always go to a human, even if the FAQ seems to cover them.
SENSITIVE = {"refund", "cancellation", "contract_change", "gdpr", "security", "legal", "churn_threat"}
MIN_CONFIDENCE = 0.7

_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]){10,30}\b")
_CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")


def mask_payment(text: str) -> str:
    return _CARD.sub("[REDACTED]", _IBAN.sub("[REDACTED]", text or ""))


def load_faq(path: str = str(Path(__file__).parent / "faq.md")) -> dict[str, str]:
    text = Path(path).read_text()
    faq = {m.group(1): m.group(0).strip()
           for m in re.finditer(r"^## (F\d\d) .*?(?=^## |^---)", text, re.M | re.S)}
    faq["RULES"] = text.split("## The client's rules for the support team", 1)[1].strip()
    return faq


def make_tools(ticket: dict, post: Callable[[str, dict], str], verify: Callable[..., dict],
               faq: dict) -> tuple[list[Callable], dict]:
    """Build the three action tools for ONE ticket. The ticket id is bound here, never chosen by the model."""
    decision: dict = {}

    def check(language, category, priority, confidence):
        if decision.get("outcome"):
            return "already decided for this ticket; stop"
        if language not in LANGUAGES:
            return f"language must be one of {sorted(LANGUAGES)}"
        if category not in CATEGORIES:
            return f"category must be one of {sorted(CATEGORIES)}"
        if priority not in PRIORITIES:
            return f"priority must be one of {sorted(PRIORITIES)}"
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            return "confidence must be a number from 0 to 1"
        return None

    def refuse(why: str) -> dict:
        decision.setdefault("refusals", []).append(why)
        return {"status": "refused", "error": why}

    def send(action: str, body: dict, **extra) -> dict:
        decision.update(action=action, body=body, **extra)
        decision["outcome"] = post(action, body)
        return {"status": "done", "outcome": decision["outcome"]}

    def reply(language: str, category: str, priority: str, reason: str, confidence: float,
              sensitive_topics: list[str], faq_ids: list[str], draft_reply: str) -> dict:
        """Send an answer to the customer. Only when the cited help-centre entries fully answer the ticket.

        Args:
            language: language the customer wrote in: nl, en or de.
            category: bug, billing, feature_request, question or other.
            priority: P1, P2, P3 or P4.
            reason: one or two English sentences: why this category, priority and action.
            confidence: 0 to 1, how sure you are that this reply is correct and complete.
            sensitive_topics: any of refund, cancellation, contract_change, gdpr, security, legal, churn_threat
                that the ticket touches. Empty list if none.
            faq_ids: the help-centre entries (e.g. ["F01"]) the reply is based on.
            draft_reply: the full reply in the customer's language, only using facts from the cited entries.
        """
        if err := check(language, category, priority, confidence):
            return refuse(err)
        if sensitive_topics:
            return refuse(f"client rule: {sensitive_topics} always go to a human; use handoff instead")
        if not faq_ids or any(f not in faq or f == "RULES" for f in faq_ids):
            return refuse("reply must cite valid help-centre ids F01-F12; if none answers it, use handoff instead")
        if confidence < MIN_CONFIDENCE:
            return refuse(f"confidence below {MIN_CONFIDENCE}; use handoff instead")
        draft = mask_payment(draft_reply)
        v = verify(ticket=ticket, draft=draft, faq_texts=[faq[f] for f in faq_ids], language=language)
        decision["verification"] = v
        if not v.get("grounded_in_faq") or v.get("detected_language") != language:
            return refuse(f"reply check failed ({v.get('issue') or 'wrong language'}); use handoff instead")
        body = dict(language=language, category=category, priority=priority, reason=mask_payment(reason),
                    draft_reply=draft, confidence=confidence)
        return send("reply", body, faq_ids=faq_ids)

    def handoff(language: str, category: str, priority: str, reason: str, confidence: float,
                sensitive_topics: list[str], handoff_note: str) -> dict:
        """Hand the ticket to the human support team. Use when unsure, when the help centre does not answer it,
        or when a client rule says a human must handle it.

        Args:
            language: language the customer wrote in: nl, en or de.
            category: bug, billing, feature_request, question or other.
            priority: P1, P2, P3 or P4.
            reason: one or two English sentences: why this category, priority and action.
            confidence: 0 to 1, how sure you are about category and priority.
            sensitive_topics: any of refund, cancellation, contract_change, gdpr, security, legal, churn_threat.
            handoff_note: in English: what the customer wants, key facts, what the agent should do next.
        """
        if err := check(language, category, priority, confidence):
            return refuse(err)
        body = dict(language=language, category=category, priority=priority, reason=mask_payment(reason),
                    handoff_note=mask_payment(handoff_note), confidence=confidence)
        return send("handoff", body, sensitive_topics=sensitive_topics)

    def close(language: str, category: str, priority: str, reason: str, confidence: float) -> dict:
        """Close without answering. Only for spam or empty tickets.

        Args:
            language: language of the ticket: nl, en or de.
            category: usually other.
            priority: usually P4.
            reason: one English sentence: why it is spam or empty.
            confidence: 0 to 1.
        """
        if err := check(language, category, priority, confidence):
            return refuse(err)
        body = dict(language=language, category=category, priority=priority, reason=mask_payment(reason),
                    confidence=confidence)
        return send("close", body)

    return [reply, handoff, close], decision
