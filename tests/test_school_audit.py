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


LAB = {"escuela.cl": {"queries": 5000, "clients": 45}}


def test_decide_referrers():
    # Sitios abiertos justo antes de un juego bloqueado (relay de Eaglercraft, GameDistribution...).
    reports = [
        {"site": "a",
         "domains": {**LAB, "eagler-copia.com": {"queries": 8, "clients": 3},
                     "fuentes.com": {"queries": 900, "clients": 40}, "friv-clon.net": {"queries": 6, "clients": 2},
                     "office.com": {"queries": 554, "clients": 45}},
         "referrers": {"eagler-copia.com": {"queries": 6, "clients": 3},
                       "friv-clon.net": {"queries": 5, "clients": 2},
                       # Se consulta todo el tiempo: que caiga cerca de un bloqueo es casualidad.
                       "fuentes.com": {"queries": 20, "clients": 9},
                       # Todo el laboratorio: es Windows/Office, no un alumno abriendo una copia.
                       "office.com": {"queries": 417, "clients": 45},
                       # Muy visitado y sin cara de juego.
                       "popular.com": {"queries": 9, "clients": 3},
                       # Nombres de red local.
                       "wpad.internal": {"queries": 9, "clients": 3}, "api.null": {"queries": 9, "clients": 3},
                       # Un solo equipo no basta.
                       "un-pc.com": {"queries": 4, "clients": 1},
                       "permitido.com": {"queries": 9, "clients": 3},
                       "descartado.com": {"queries": 9, "clients": 3}}},
    ]
    res = decide(reports, {"rejected": ["descartado.com"]}, set(), {"permitido.com"}, set(),
                 games("eagler-copia.com"), popular={"popular.com"})
    # Origen + cara de juego: se agrega aunque lo haya visto un solo colegio.
    assert res["add"] == ["eagler-copia.com"]
    assert res["added"][0] == {"domain": "eagler-copia.com", "queries": 8, "clients": 3, "sites": 1}
    # Origen sin cara de juego: pendiente, con la señal para el panel. No se vuelve a revisar
    # como dominio común.
    assert res["pending"] == [{"domain": "friv-clon.net", "queries": 6, "clients": 2, "sites": 1, "via": "referrer"}]


def test_decide_referrers_noisy_site():
    # Colegio donde casi todo cae cerca de un bloqueo (Windows consultando msn.com): solo se
    # destaca lo que supera con creces ese ruido de fondo.
    doms = {**LAB, "copia.io": {"queries": 4, "clients": 2}, "ruido.com": {"queries": 4000, "clients": 20}}
    refs = {"copia.io": {"queries": 4, "clients": 2}, "ruido.com": {"queries": 2400, "clients": 20},
            "escuela.cl": {"queries": 2500, "clients": 45}}
    res = decide([{"site": "a", "domains": doms, "referrers": refs}], {}, set(), set(), set(), games())
    assert [p["domain"] for p in res["pending"]] == ["copia.io"]


def test_decide_referrers_without_popular_list():
    # Sin la lista de sitios populares no se proponen sitios de origen sin cara de juego, pero los
    # que parecen juego se agregan igual.
    reports = [{"site": "a", "domains": dict(LAB),
                "referrers": {"copia.io": {"queries": 4, "clients": 2}, "juego.io": {"queries": 4, "clients": 2}}}]
    res = decide(reports, {}, set(), set(), set(), games("juego.io"), popular=None)
    assert res["add"] == ["juego.io"] and res["pending"] == []


def test_decide_referrers_cap_and_old_reports():
    reports = [{"site": "a", "domains": dict(LAB),
                "referrers": {f"r{i}.com": {"queries": 3, "clients": 2} for i in range(60)}},
               # Un reporte de una versión anterior no trae referrers.
               {"site": "b", "domains": {"juego.com": {"queries": 9, "clients": 3}}}]
    res = decide(reports, {}, set(), set(), set(), games("juego.com"))
    assert sum(1 for p in res["pending"] if p.get("via") == "referrer") == 50
    assert [p["domain"] for p in res["pending"] if "via" not in p] == ["juego.com"]


def test_decide_never_proposes_shared_suffixes():
    # Shield < v1.1.24 reporta classroom.it.com como it.com: un dominio compartido completo.
    reports = [{"site": s, "domains": {**LAB, "it.com": {"queries": 9, "clients": 3}}} for s in ("a", "b")]
    res = decide(reports, {"approved": ["us.com"]}, set(), set(), set(), games("it.com", "us.com"))
    assert res["add"] == [] and res["pending"] == []


def test_decide_skips_what_the_validator_would_reject():
    # Un aprobado que el validador rechazaría (top 10.000 sin aprobar, hosting completo) no debe
    # entrar: si entrara, se revertiría toda la corrida. El resto se agrega igual.
    reports = [{"site": s, "domains": {**LAB, "juego.com": {"queries": 9, "clients": 3}}} for s in ("a", "b")]
    res = decide(reports, {"approved": ["office.com", "vercel.app", "otrojuego.io"]}, set(), set(), set(),
                 games("juego.com"))
    assert sorted(res["add"]) == ["juego.com", "otrojuego.io"]
    assert res["applied"] == ["otrojuego.io"]
    # vercel.app ya lo frena la regla de dominios compartidos; office.com, el validador.
    assert res["invalid"] == ["office.com"]
