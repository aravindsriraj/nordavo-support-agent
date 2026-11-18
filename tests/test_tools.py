from agent import load_faq, make_tools, mask_payment

TICKET = {"id": "T001", "subject": "Wachtwoord", "body": "Hoe reset ik mijn wachtwoord?"}
OK = {"english_back_translation": "x", "detected_language": "nl", "grounded_in_faq": True, "issue": ""}
CLOSE = dict(language="nl", category="other", priority="P4", reason="spam", confidence=0.9)
BASE = dict(language="nl", category="question", priority="P4", reason="FAQ F01", confidence=0.9, sensitive_topics=[])


def setup(verdict=OK):
    posts = []
    tools, decision = make_tools(TICKET, lambda a, b: posts.append((a, b)) or "posted",
                                 lambda **kw: verdict, load_faq())
    reply, handoff, close = tools
    return reply, handoff, close, posts, decision


def test_load_faq_has_12_entries_and_rules():
    faq = load_faq()
    assert [f"F{i:02d}" for i in range(1, 13)] == sorted(k for k in faq if k != "RULES")
    assert "refunds" in faq["RULES"]


def test_mask_payment():
    assert mask_payment("IBAN NL91ABNA0417164300 ok") == "IBAN [REDACTED] ok"
    assert mask_payment("kaart 4111 1111 1111 1111.") == "kaart [REDACTED]."
    assert mask_payment("T005 costs €4 per month, 12 users") == "T005 costs €4 per month, 12 users"


def test_reply_refused_for_sensitive_topic():
    reply, *_, posts, _ = setup()
    r = reply(**{**BASE, "sensitive_topics": ["refund"]}, faq_ids=["F01"], draft_reply="Hoi")
    assert r["status"] == "refused" and posts == []


def test_reply_refused_without_valid_faq_id():
    for ids in ([], ["F99"]):
        reply, *_, posts, _ = setup()
        assert reply(**BASE, faq_ids=ids, draft_reply="Hoi")["status"] == "refused"
        assert posts == []


def test_reply_refused_low_confidence():
    reply, *_, posts, _ = setup()
    assert reply(**{**BASE, "confidence": 0.69}, faq_ids=["F01"], draft_reply="Hoi")["status"] == "refused"


def test_reply_refused_when_verifier_rejects():
    for bad in ({**OK, "grounded_in_faq": False}, {**OK, "detected_language": "en"}):
        reply, *_, posts, _ = setup(bad)
        assert reply(**BASE, faq_ids=["F01"], draft_reply="Hoi")["status"] == "refused"
        assert posts == []


def test_reply_posts_masked_draft():
    reply, *_, posts, decision = setup()
    r = reply(**BASE, faq_ids=["F01"], draft_reply="Hoi, uw IBAN NL91ABNA0417164300")
    assert r == {"status": "done", "outcome": "posted"}
    action, body = posts[0]
    assert action == "reply" and "[REDACTED]" in body["draft_reply"]
    assert set(body) == {"language", "category", "priority", "reason", "draft_reply", "confidence"}
    assert decision["action"] == "reply" and decision["verification"] == OK


def test_invalid_enum_refused():
    reply, handoff, close, posts, _ = setup()
    assert close(**{**CLOSE, "category": "spam"})["status"] == "refused"
    assert posts == []


def test_second_action_refused():
    reply, handoff, close, posts, _ = setup()
    assert handoff(**BASE, handoff_note="Customer asks X")["status"] == "done"
    r = close(**CLOSE)
    assert r["status"] == "refused" and "already decided" in r["error"]
    assert len(posts) == 1


def test_handoff_note_masked():
    _, handoff, _, posts, _ = setup()
    handoff(**{**BASE, "sensitive_topics": ["refund"]}, handoff_note="Refund to NL91ABNA0417164300")
    assert posts[0][1]["handoff_note"] == "Refund to [REDACTED]"
    assert set(posts[0][1]) == {"language", "category", "priority", "reason", "handoff_note", "confidence"}
