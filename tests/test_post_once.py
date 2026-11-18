import pytest

from helpdesk import AlreadyHandled, HelpdeskError, State, post_once


class FakeHD:
    def __init__(self, ticket=None, raises=None):
        self.ticket = ticket or {"id": "T001", "handled": None}
        self.raises = raises
        self.posts, self.gets = [], 0

    def get_ticket(self, id):
        self.gets += 1
        return self.ticket

    def post_action(self, id, action, body):
        if self.raises:
            raise self.raises
        self.posts.append((id, action, body))
        return {"ok": True}


def test_posts_and_marks_state(tmp_path):
    p = str(tmp_path / "s.json")
    hd = FakeHD()
    assert post_once(hd, State(p), "T001", "reply", {"a": 1}) == "posted"
    assert hd.posts == [("T001", "reply", {"a": 1})]
    assert State(p).done("T001")


def test_skips_when_state_says_done(tmp_path):
    s = State(str(tmp_path / "s.json"))
    s.mark("T001", "posted")
    hd = FakeHD()
    assert post_once(hd, s, "T001", "reply", {}) == "already_handled"
    assert hd.posts == [] and hd.gets == 0


def test_skips_when_server_says_handled(tmp_path):
    s = State(str(tmp_path / "s.json"))
    hd = FakeHD(ticket={"id": "T001", "handled": {"action": "reply"}})
    assert post_once(hd, s, "T001", "reply", {}) == "already_handled"
    assert hd.posts == []
    assert s.done("T001")


def test_409_counts_as_already_handled(tmp_path):
    s = State(str(tmp_path / "s.json"))
    hd = FakeHD(raises=AlreadyHandled(409))
    assert post_once(hd, s, "T001", "reply", {}) == "already_handled"
    assert s.done("T001")


def test_other_error_propagates_and_state_untouched(tmp_path):
    s = State(str(tmp_path / "s.json"))
    hd = FakeHD(raises=HelpdeskError(503))
    with pytest.raises(HelpdeskError):
        post_once(hd, s, "T001", "reply", {})
    assert not s.done("T001")
