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


def test_decide_ignores_custom_filter_rules():
    # Las reglas del filtro personalizado son decisión de cada colegio: nunca se usan,
    # aunque un reporte antiguo las traiga.
    reports = [report(s, {}, manual=["manual.com"], unblocks=["juego1.com"]) for s in ("a", "b")]
    res = decide(reports, {}, set(), set(), set(), games("manual.com"))
    assert res["add"] == [] and res["pending"] == []


def test_decide_approved():
    res = decide([], {"approved": ["aprobado.com", "permitido.com"]}, set(), {"permitido.com"}, set(), games())
    assert res["add"] == ["aprobado.com"]
    assert res["applied"] == ["aprobado.com"]


def test_decide_cap():
    reports = [report(s, {f"j{i}.com": {"queries": 9, "clients": 3} for i in range(5)}) for s in ("a", "b")]
    res = decide(reports, {}, set(), set(), set(), games(*[f"j{i}.com" for i in range(5)]), max_add=2)
    assert len(res["add"]) == 2 and res["pending"] == []
