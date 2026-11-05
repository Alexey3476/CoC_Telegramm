import asyncio
from types import SimpleNamespace

from app import bot as module
from app.bindings_storage import Binding, BindingsStorage
from app.clan_poll import ClanPollStore


class DummyClient:
    def __init__(self,*args,**kwargs):
        pass
    async def __aenter__(self):
        return self
    async def __aexit__(self,*args):
        return False


def bind(uid,tag):
    return Binding(uid,-1001,tag,None,"Member","2026-11-05")


def test_clan_poll_only_counts_one_active_owner_even_with_alts(monkeypatch,tmp_path):
    path=str(tmp_path/"links.db")
    links=BindingsStorage(path)
    links.upsert_binding(bind(42,"#PLAY1"))
    links.upsert_binding(bind(42,"#PLAY2"))
    links.upsert_binding(bind(77,"#GONE"))
    polls=ClanPollStore(path)
    polls.create("poll1",-1001,10,[{"tag":"#PLAY1","name":"One"},{"tag":"#PLAY2","name":"Two"}])
    monkeypatch.setattr(module,"settings",SimpleNamespace(request_timeout_seconds=2))
    monkeypatch.setattr(module.httpx,"AsyncClient",DummyClient)

    async def fake_clan(client,path):
        assert path=="/clan"
        return {"memberList":[{"tag":"#PLAY1"},{"tag":"#PLAY2"}]}
    monkeypatch.setattr(module,"fetch_json",fake_clan)
    ctx=SimpleNamespace(application=SimpleNamespace(
        bot_data={"storage":links,"clan_poll_store":polls}))
    def answer(uid,choices):
        return SimpleNamespace(poll_answer=SimpleNamespace(
            poll_id="poll1",user=SimpleNamespace(id=uid),option_ids=choices))
    asyncio.run(module.deputy_poll_answer(answer(42,[0]),ctx))
    asyncio.run(module.deputy_poll_answer(answer(42,[1]),ctx))
    asyncio.run(module.deputy_poll_answer(answer(77,[0]),ctx))
    assert sum(x["votes"] for x in polls.count("poll1",{42,77}))==1
    assert polls.count("poll1",{42})[0]["name"]=="Two"
    asyncio.run(module.deputy_poll_closed(
        SimpleNamespace(poll=SimpleNamespace(id="poll1",is_closed=True)),ctx))
    assert not polls.get("poll1")["open"]
