import pytest

from app.tags import assign_game_tag


class StubMember:
    def __init__(self, status):
        self.status = status


class StubBot:
    token = "dummy-token"
    def __init__(self, status):
        self.status = status

    async def get_chat_member(self, chat_id, user_id):
        return StubMember(self.status)


class Context:
    def __init__(self, status):
        self.bot = StubBot(status)


@pytest.mark.asyncio
async def test_admin_title_is_not_overwritten():
    assert await assign_game_tag(Context("administrator"), -100123, 8, "Lex") is False
    assert await assign_game_tag(Context("creator"), -100123, 8, "Lex") is False


@pytest.mark.asyncio
async def test_empty_emoji_only_nick_is_not_written():
    assert await assign_game_tag(Context("member"), -100123, 8, "🐲⚔") is False
