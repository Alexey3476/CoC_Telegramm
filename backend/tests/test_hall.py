from app.hall import hall_of_fame


def test_hall_uses_donation_season_and_raid_members_not_clan_games():
    clan={"tag":"#OUR","memberList":[
        {"name":"Lex","tag":"#A","role":"coLeader","donations":20},
        {"name":"B","tag":"#B","role":"member","donations":150},
    ]}
    raid={"members":[{"tag":"#A","capitalResourcesLooted":100},
                     {"tag":"#B","capitalResourcesLooted":1500}]}
    result=hall_of_fame(clan,[],raid)
    assert result["donations"][0]["name"] == "B"
    assert result["raids"][0]["score"] == 1500
    assert result["clanGamesAvailable"] is False
    assert result["war"] == []
