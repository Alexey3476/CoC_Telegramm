import asyncio
import pytest
from app import main as backend


def test_cwl_saved_when_regular_war_endpoint_fails(monkeypatch):
    saved=[]
    async def bad_regular(client, cache):
        raise RuntimeError("regular war unavailable in CWL")
    async def good_cwl(client, cache):
        return {"state":"inWar"}, [{"state":"warEnded","startTime":"20261105T120000Z",
                    "clan":{"tag":"#A"},"opponent":{"tag":"#B"}}]
    async def stop_after_one_cycle(seconds):
        raise asyncio.CancelledError
    class History:
        def save(self, war):
            saved.append(war)
            return True
    monkeypatch.setattr(backend,"get_regular_war",bad_regular)
    monkeypatch.setattr(backend,"get_league_wars",good_cwl)
    monkeypatch.setattr(backend.asyncio,"sleep",stop_after_one_cycle)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(backend.collect_war_history(None,None,History()))
    assert len(saved)==1
    assert saved[0]["_warKind"]=="cwl"
