import asyncio

import agent


def test_format_ticket_handles_none_body():
    text = agent.format_ticket({"id": "T1", "subject": None, "body": None, "channel": "email"})
    assert "<ticket>" in text and "</ticket>" in text and "None" not in text


def run_with(monkeypatch, fake):
    monkeypatch.setattr(agent, "_run_agent", fake)
    posts = []
    d = asyncio.run(agent.decide({"id": "T1", "subject": "x", "body": "y"},
                                 lambda a, b: posts.append((a, b)) or "posted",
                                 verify=lambda **kw: {}))
    return d, posts


def test_fallback_handoff_when_agent_does_not_act(monkeypatch):
    async def fake(ag, text):
        return {"input": 10, "output": 5}
    d, posts = run_with(monkeypatch, fake)
    assert [a for a, _ in posts] == ["handoff"]
    assert "no decision" in posts[0][1]["reason"].lower()
    assert d["fallback"] is True and d["outcome"] == "posted"
    assert d["tokens"] == {"input": 10, "output": 5}


def test_fallback_handoff_when_model_raises(monkeypatch):
    async def fake(ag, text):
        raise RuntimeError("model down")
    d, posts = run_with(monkeypatch, fake)
    assert [a for a, _ in posts] == ["handoff"] and d["fallback"] is True


def test_helpdesk_error_is_raised_not_hidden_by_fallback(monkeypatch):
    import pytest
    from helpdesk import HelpdeskError

    async def fake(ag, text):
        raise HelpdeskError(503)
    with pytest.raises(HelpdeskError):
        run_with(monkeypatch, fake)
