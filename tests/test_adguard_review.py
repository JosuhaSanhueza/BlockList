import json
from datetime import datetime, timezone

from scripts.adguard_review import (covered, extract_unblocked, is_whitelisted, parse_time,
                                     parse_user_rules, parse_yaml_user_rules,
                                     read_querylog_file, registrable)


def test_registrable_apex_and_subdomains():
    assert registrable("www.example.com") == "example.com"
    assert registrable("cdn.assets.example.com") == "example.com"
    assert registrable("foo.co.uk") == "foo.co.uk"
    assert registrable("a.b.foo.co.uk") == "foo.co.uk"


def test_registrable_shared_hosting_keeps_subdomain():
    assert registrable("slope.github.io") == "slope.github.io"
    assert registrable("www.slope.github.io") == "slope.github.io"
    assert registrable("x.y.mygame.pages.dev") == "mygame.pages.dev"


def test_parse_user_rules_only_simple_domain_rules():
    rules = ["||game.com^", "@@||ok.com^", "! comentario", "||site.com/path^", "||Foo.NET^", "/regex/"]
    assert parse_user_rules(rules) == ["game.com", "foo.net"]


def test_extract_unblocked_counts_and_ignores_blocked():
    entries = [
        {"reason": "NotFilteredNotFound", "question": {"name": "a.game.com"}, "client": "10.0.0.1"},
        {"reason": "NotFilteredNotFound", "question": {"name": "b.game.com"}, "client": "10.0.0.2"},
        {"reason": "FilteredBlackList", "question": {"name": "blocked.com"}, "client": "10.0.0.1"},
        {"reason": "NotFilteredWhiteList", "question": {"name": "allowed.com"}, "client": "10.0.0.1"},
        {"reason": "NotFilteredNotFound", "question": {"name": "1.0.0.127.in-addr.arpa"}, "client": "x"},
    ]
    assert extract_unblocked(entries) == {"game.com": {"queries": 2, "clients": 2}}


def test_covered_and_whitelist():
    assert covered("sub.game.com", {"game.com"})
    assert not covered("game.com", {"sub.game.com"})
    assert is_whitelisted("x.fandom.com", {"fandom.com"}, set())
    assert not is_whitelisted("x.fandom.com", {"fandom.com"}, {"x.fandom.com"})


def test_parse_time_with_nanoseconds():
    t = parse_time("2026-10-10T21:20:00.123456789-03:00")
    assert t.year == 2026 and t.hour == 21


def test_parse_yaml_user_rules():
    y = "dns:\n  port: 53\nuser_rules:\n  - '||a.com^'\n  - \"@@||b.com^\"\n  - ||c.org^\nother: 1\n"
    assert parse_yaml_user_rules(y) == ["||a.com^", "@@||b.com^", "||c.org^"]
    assert parse_yaml_user_rules("user_rules: []\nx: 1\n") == []


def test_read_querylog_file(tmp_path):
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {"T": now, "QH": "game.com", "IP": "10.0.0.5", "Result": {"IsFiltered": False, "Reason": 0}},
        {"T": now, "QH": "bad.com", "IP": "10.0.0.5", "Result": {"IsFiltered": True, "Reason": 3}},
        {"T": "2020-01-01T00:00:00Z", "QH": "old.com", "IP": "10.0.0.6", "Result": {}},
    ]
    f = tmp_path / "querylog.json"
    f.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")
    got = extract_unblocked(read_querylog_file(str(f), 24))
    assert got == {"game.com": {"queries": 1, "clients": 1}}
