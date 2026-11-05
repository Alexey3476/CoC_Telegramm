"""End-to-end mocked API coverage for seven CWL slots and current place."""
import asyncio
from types import SimpleNamespace

from app import coc_client as api


def test_cwl_seven_rounds_group_position_from_all_clan_wars(monkeypatch):
    group = {
        "state":"inWar",
        "clans":[{"tag":"#P0L","name":"Troublemakers"},
                 {"tag":"#Q0V","name":"Enemy"},
                 {"tag":"#C","name":"Other C"},
                 {"tag":"#D","name":"Other D"}],
        "rounds":[{"warTags":[f"#W{i}", "#0"]} for i in range(1, 8)],
    }
    def war(tag, our_stars, enemy_stars, reversed=False):
        ours={"tag":"#P0L","name":"Troublemakers","stars":our_stars,
              "destructionPercentage":95.0}
        enemy={"tag":"#Q0V","name":"Enemy","stars":enemy_stars,
               "destructionPercentage":90.0}
        return {"_leagueWarTag":tag,"state":"warEnded",
                "startTime":"20261101T000000.000Z",
                "clan":enemy if reversed else ours,
                "opponent":ours if reversed else enemy}
    wars=[war("#W1",35,30),war("#W2",30,36,reversed=True),
          war("#W3",33,31)]
    async def fake_get(client, cache, *, include_all=False):
        assert include_all is True
        return group, wars
    monkeypatch.setattr(api, "get_league_wars", fake_get)
    monkeypatch.setattr(api, "settings", SimpleNamespace(coc_clan_tag="#P0L"))
    result=asyncio.run(api.get_cwl_summary(None, None))
    assert result["scheduledRounds"] == 7
    assert len(result["rounds"]) == 7
    assert [r["result"] for r in result["rounds"][:3]] == ["win","loss","win"]
    assert all(r["result"] == "upcoming" for r in result["rounds"][3:])
    board=result["standings"]
    assert board["myPlace"] == 1
    ours=next(p for p in board["clans"] if p["tag"]=="#P0L")
    assert ours["attackStars"] == 98
    assert ours["winBonusStars"] == 20
    assert ours["stars"] == 118
    assert not board["seasonCompleted"]


def test_group_six_clans_can_have_fewer_than_seven_rounds(monkeypatch):
    group={"state":"inWar","clans":[{"tag":"#P0L"}],
           "rounds":[{"warTags":["#0"]} for _ in range(5)]}
    async def fake_get(client, cache, *, include_all=False):
        return group, []
    monkeypatch.setattr(api, "get_league_wars", fake_get)
    monkeypatch.setattr(api, "settings", SimpleNamespace(coc_clan_tag="#P0L"))
    summary=asyncio.run(api.get_cwl_summary(None,None))
    assert summary["scheduledRounds"] == 5
    assert len(summary["rounds"]) == 5
    assert all(x["result"]=="upcoming" for x in summary["rounds"])
