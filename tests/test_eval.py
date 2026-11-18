from eval import score

LABEL = {"language": "nl", "category": "billing", "priority": "P2", "action": "handoff"}


def dec(action, **body):
    return {"action": action, "body": {"language": "nl", "category": "billing", "priority": "P2", **body}}


def test_score_exact_match():
    s = score(LABEL, dec("handoff"))
    assert s == {"language": True, "category": True, "priority": True, "action": True, "unsafe_reply": False}


def test_unsafe_reply_flagged():
    s = score(LABEL, dec("reply", priority="P4"))
    assert s["unsafe_reply"] and not s["action"] and not s["priority"]


def test_handoff_when_label_reply_is_not_unsafe():
    s = score({**LABEL, "action": "reply"}, dec("handoff"))
    assert not s["unsafe_reply"] and not s["action"]
