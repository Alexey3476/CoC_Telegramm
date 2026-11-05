from app.captain import is_captain, captain_report_text
from app.bot import main_menu_keyboard


def test_captain_role_requires_current_verified_tag():
    members = [{"tag": "#AAA", "role": "leader"},
               {"tag": "#BBB", "role": "coLeader"},
               {"tag": "#CCC", "role": "admin"}]
    assert is_captain(members, "#AAA")
    assert is_captain(members, "#BBB")
    assert not is_captain(members, "#CCC")
    assert not is_captain(members, "#DDD")


def test_captain_button_is_not_shown_to_regular_users():
    base = main_menu_keyboard()
    privileged = main_menu_keyboard(captain=True)
    assert len(privileged.inline_keyboard) == len(base.inline_keyboard) + 1


def test_captain_report_does_not_call_donations_last_online():
    txt = captain_report_text({"clanName": "<Bad>", "members": {"total": 42},
        "war": {"attacksDone": 12, "attacksRemaining": 18},
        "activity": {"mostActive": [{"name": "A&B", "donations": 20}]}})
    assert "&lt;Bad&gt;" in txt
    assert "A&amp;B" in txt
    assert "12" in txt and "18" in txt
