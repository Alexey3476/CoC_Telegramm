from datetime import datetime, timezone
from app.progress import ProgressStore


def snapshot(tag, townhall, hero):
    return {"tag":tag,"townHallLevel":townhall,
            "heroes":[{"name":"King","level":hero}]}


def test_timeline_per_tag_and_different_windows(tmp_path):
    store=ProgressStore(str(tmp_path/"players.sqlite"))
    times=[datetime(2026,10,1,tzinfo=timezone.utc),
           datetime(2026,10,20,tzinfo=timezone.utc),
           datetime(2026,11,5,tzinfo=timezone.utc)]
    for level,when in zip([16,17,18], times):
        store.record(snapshot("#A",level,level+30),when)
    store.record(snapshot("#B",12,50),times[-1])
    result=store.timeline("#A",days=30,now=times[-1])
    assert result["snapshotCount"]==2
    assert result["changes"]["townHallLevel"]["delta"]==1
    assert result["changes"]["heroes"]["King"]["delta"]==1
    all_time=store.timeline("#A",days=0,now=times[-1])
    assert all_time["snapshotCount"]==3
    assert all_time["changes"]["townHallLevel"]["delta"]==2
    assert not store.timeline("#B",days=30,now=times[-1])["historyAvailable"]
    assert store.timeline("#A",days=7,now=times[-1])["snapshotCount"]==1
