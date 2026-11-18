import pytest

from helpdesk import AlreadyHandled, HelpdeskError, post_once


class FakeHD:
    def __init__(self, handled=None, raises=None, handled_after_post=None):
        self.handled, self.raises, self.handled_after_post = handled, raises, handled_after_post
        self.posts = []

    def get_ticket(self, id):
        return {"id": id, "handled": self.handled}

    def post_action(self, id, action, body):
        if self.raises:
            self.handled = self.handled_after_post
            raise self.raises
        self.posts.append((id, action, body))
        return {"ok": True}


def test_posts_when_open():
    hd = FakeHD()
    assert post_once(hd, "T001", "reply", {"a": 1}) == "posted"
    assert hd.posts == [("T001", "reply", {"a": 1})]


def test_skips_when_server_says_handled():
    hd = FakeHD(handled={"action": "reply"})
    assert post_once(hd, "T001", "reply", {}) == "already_handled"
    assert hd.posts == []


def test_409_counts_as_already_handled():
    assert post_once(FakeHD(raises=AlreadyHandled(409)), "T001", "reply", {}) == "already_handled"


def test_network_error_on_post_then_saved_is_already_handled():
    hd = FakeHD(raises=HelpdeskError(0), handled_after_post={"action": "reply"})
    assert post_once(hd, "T001", "reply", {}) == "already_handled"


def test_network_error_on_post_not_saved_propagates():
    with pytest.raises(HelpdeskError):
        post_once(FakeHD(raises=HelpdeskError(0)), "T001", "reply", {})


def test_other_error_propagates():
    with pytest.raises(HelpdeskError):
        post_once(FakeHD(raises=HelpdeskError(503)), "T001", "reply", {})
