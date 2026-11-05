from app.bot import attacks_used, extract_tag, normalize_tag


def test_extract_tag_from_message():
    assert extract_tag("мой #2PRGP0L22 вот") == "#2PRGP0L22"
    assert extract_tag("пожалуйста") is None


def test_normalize_tag():
    assert normalize_tag(" 2prgp0l22 ") == "#2PRGP0L22"


def test_attacks_used():
    assert attacks_used({"attacks": [{"stars": 2}]}) == 1
    assert attacks_used({"attacks": 2}) == 2
    assert attacks_used({}) == 0
