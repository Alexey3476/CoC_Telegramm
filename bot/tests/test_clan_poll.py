from app.clan_poll import ClanPollStore


def test_clan_poll_one_vote_per_user_revoting_and_retraction(tmp_path):
    p = str(tmp_path / "linked.db")
    store = ClanPollStore(p)
    choices = [{"tag": "#P1", "name": "Lex"}, {"tag": "#P2", "name": "Alex"}]
    store.create("poll-a", -1001, 777, choices)
    assert store.record("poll-a", 42, [0], eligible=True)
    assert store.record("poll-a", 42, [1], eligible=True)
    assert not store.record("poll-a", 99, [0], eligible=False)
    assert sum(x["votes"] for x in store.count("poll-a", {42, 99})) == 1
    assert store.count("poll-a", {42})[0]["name"] == "Alex"
    assert sum(x["votes"] for x in ClanPollStore(p).count("poll-a", {42})) == 1
    store.record("poll-a", 42, [], eligible=True)
    assert sum(x["votes"] for x in store.count("poll-a", {42})) == 0
    assert store.close("poll-a") is None
    assert store.get("poll-a")["open"] is False
    assert not store.record("poll-a", 42, [1], eligible=True)


def test_only_verified_clan_owner_counted_not_extra_alts(tmp_path):
    store = ClanPollStore(str(tmp_path / "clan.db"))
    store.create("vote", -1001, 456,
                 [{"tag":"#TAG1","name":"A"},{"tag":"#TAG2","name":"B"}])
    store.record("vote", 10, [0], True)
    store.record("vote", 20, [1], True)
    eligible_owners = {10}  # Same voter 10 could own 4 tags; one owner ID.
    counts = store.count("vote", eligible_owners)
    assert next(x["votes"] for x in counts if x["name"] == "A") == 1
    assert next(x["votes"] for x in counts if x["name"] == "B") == 0
