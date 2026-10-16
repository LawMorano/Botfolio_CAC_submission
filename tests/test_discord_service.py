import json

from services import discord_service


def test_notify_is_disabled_without_webhook(monkeypatch):
    started = []
    monkeypatch.setattr(discord_service.threading, "Thread", lambda **kwargs: started.append(kwargs))

    assert discord_service.notify_design_published(
        "", design_url="https://example.test/designs/1", title="Arm", author="Ada"
    ) is False
    assert started == []


def test_webhook_payload_has_design_link_and_disables_mentions(monkeypatch):
    captured = {}

    class ImmediateThread:
        def __init__(self, *, target, args, **kwargs):
            self.target = target
            self.args = args

        def start(self):
            self.target(*self.args)

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b""

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(discord_service.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(discord_service.urllib.request, "urlopen", fake_urlopen)

    assert discord_service.notify_design_published(
        "https://discord.invalid/webhook-secret",
        design_url="https://botfolio.example/designs/42",
        title="Compact Intake",
        author="Ada",
        description="A compact FTC intake.",
        image_url="https://botfolio.example/uploads/intake.jpg",
    ) is True

    payload = captured["payload"]
    assert payload["allowed_mentions"] == {"parse": []}
    assert payload["embeds"][0]["url"] == "https://botfolio.example/designs/42"
    assert payload["embeds"][0]["title"] == "Compact Intake"
    assert payload["embeds"][0]["image"] == {
        "url": "https://botfolio.example/uploads/intake.jpg"
    }
    assert captured["timeout"] == 5
