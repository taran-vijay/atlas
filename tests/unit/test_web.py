from atlas.web import _PAGE, AtlasWebApp


class _FakeAssistant:
    async def handle_message(self, user_input: str) -> str:
        return f"Reply: {user_input}"


def test_web_app_runs_the_same_assistant_message_handler() -> None:
    app = AtlasWebApp(_FakeAssistant())

    assert app.chat("Hello") == "Reply: Hello"


def test_dashboard_contains_chat_surface() -> None:
    assert "Atlas — Local Assistant" in _PAGE
    assert "/api/chat" in _PAGE
    assert "Message Atlas" in _PAGE
