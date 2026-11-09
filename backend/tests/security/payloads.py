"""Общий набор инъекционных payload-ов. Каждое текстовое поле прогоняется через него."""

SQLI = [
    "' OR '1'='1",
    "'; DROP TABLE users;--",
    '" OR ""="',
    "1; SELECT pg_sleep(5)--",
    "' UNION SELECT NULL,NULL--",
    "admin'--",
    "1' AND (SELECT COUNT(*) FROM pg_tables)>0--",
]
XSS = [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    '"><svg/onload=alert(1)>',
    "javascript:alert(1)",
    "<iframe src=javascript:alert(1)>",
    "'-alert(1)-'",
]
TEMPLATE = ["{{7*7}}", "${7*7}", "#{7*7}", "{%raw%}"]
COMMAND = ["; ls -la", "| cat /etc/passwd", "`id`", "$(id)", "&& whoami"]
PATH = ["../../etc/passwd", "..\\..\\windows\\win.ini", "%2e%2e%2f"]
CONTROL = ["a\x00b", "\x00", "a\x1bb", "\r\nSet-Cookie: x=1"]
OVERSIZE = ["A" * 100_000]

ALL = SQLI + XSS + TEMPLATE + COMMAND + PATH + CONTROL + OVERSIZE
MARKUP = [p for p in XSS if "<" in p]


def assert_rejected_or_neutral(validator, payload: str) -> None:
    """Валидатор должен либо отклонить payload, либо вернуть значение без управляющих символов."""
    try:
        out = validator(payload)
    except (ValueError, TypeError):
        return
    assert isinstance(out, str)
    assert "\x00" not in out and "<" not in out and ">" not in out
