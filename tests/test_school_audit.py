from scripts.school_audit import decide


def report(site, domains, manual=(), unblocks=()):
    return {"site": site, "domains": domains, "manual": list(manual), "unblocks": list(unblocks)}


def games(*names):
    return lambda cand: [(d, m) for d, m in cand if d in names]


def test_decide_multi_and_single_school():
    reports = [
        report("a", {"juego1.com": {"queries": 10, "clients": 3}, "juego2.io": {"queries": 5, "clients": 2},
                     "escuela.cl": {"queries": 90, "clients": 20}}),
        report("b", {"juego1.com": {"queries": 4, "clients": 2}}),
    ]
    res = decide(reports, {}, set(), set(), set(), games("juego1.com", "juego2.io"))
    assert res["add"] == ["juego1.com"]
    assert res["added"][0] == {"domain": "juego1.com", "queries": 14, "clients": 5, "sites": 2}
    assert [p["domain"] for p in res["pending"]] == ["juego2.io"]


def test_decide_respects_list_whitelist_and_rejections():
    reports = [report(s, {"ya.com": {"queries": 9, "clients": 3}, "permitido.com": {"queries": 9, "clients": 3},
                          "descartado.com": {"queries": 9, "clients": 3}}) for s in ("a", "b")]
    res = decide(reports, {"rejected": ["descartado.com"]}, {"ya.com"}, {"permitido.com"}, set(),
                 games("ya.com", "permitido.com", "descartado.com"))
    assert res["add"] == [] and res["pending"] == []


def test_decide_thresholds():
    reports = [report(s, {"raro.com": {"queries": 1, "clients": 1}}) for s in ("a", "b")]
    res = decide(reports, {}, set(), set(), set(), games("raro.com"))
    assert res["add"] == []


def test_decide_manual_rules_and_approved():
    reports = [report("a", {}, manual=["manual1.com", "manual2.com"]), report("b", {}, manual=["manual1.com"])]
    res = decide(reports, {"approved": ["aprobado.com"]}, set(), set(), set(), games())
    assert set(res["add"]) == {"aprobado.com", "manual1.com"}
    assert res["applied"] == ["aprobado.com"]
    assert [p["domain"] for p in res["pending"]] == ["manual2.com"]


def test_decide_cap_and_unblocks():
    reports = [report(s, {f"j{i}.com": {"queries": 9, "clients": 3} for i in range(5)},
                      unblocks=["listado.com", "no-listado.com"]) for s in ("a", "b")]
    res = decide(reports, {}, {"listado.com"}, set(), set(), games(*[f"j{i}.com" for i in range(5)]), max_add=2)
    assert len(res["add"]) == 2 and res["pending"] == []
    assert res["unblocks"] == [{"domain": "listado.com", "queries": 0, "clients": 0, "sites": 2}]
