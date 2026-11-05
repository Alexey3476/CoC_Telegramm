import logging

from app.bot import SecretRedactingFormatter


def test_redaction_of_api_token_in_url():
    fmt = SecretRedactingFormatter("%(message)s")
    raw = "POST https://api.telegram.org/bot123456:ABC-abc_xyz/getUpdates 200"
    record = logging.LogRecord("httpx", logging.WARNING, __file__, 1, raw, (), None)
    result = fmt.format(record)
    assert "ABC-abc_xyz" not in result
    assert "/bot[REDACTED]/getUpdates" in result


def test_redaction_of_api_token_in_traceback():
    import sys
    fmt = SecretRedactingFormatter("%(message)s")
    try:
        raise ValueError("https://api.telegram.org/bot123456:ABC_secret/sendMessage")
    except ValueError:
        record = logging.LogRecord("test", logging.ERROR, __file__, 1, "Error", (),
                                   sys.exc_info())
    assert "ABC_secret" not in fmt.format(record)
