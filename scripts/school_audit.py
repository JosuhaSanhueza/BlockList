#!/usr/bin/env python3
"""Auditor diario de la lista de juegos a partir de los colegios con EscolarApp Shield.

Cada EscolarApp Shield envía una vez al día al hub (dash.escolarapp.cl) un reporte anónimo:
dominios no bloqueados vistos por al menos 2 equipos, con sus conteos. El filtro personalizado
de cada colegio NO se usa: es decisión de su informático y no debe influir en la lista común.
Este script, pensado para GitHub Actions:

  1. Descarga los reportes del día y las decisiones tomadas en el panel.
  2. Clasifica los dominios nuevos con is_game_website().
  3. Agrega a GamesBlockList.txt los juegos vistos en 2 o más colegios y lo aprobado en el
     panel (máximo --max-add por día).
  4. Deja como pendientes, para aprobar en el panel, los juegos de un solo colegio.
  5. Revisa los "sitios de origen": dominios que los equipos abrieron justo antes de una consulta
     bloqueada por la lista de juegos (p. ej. una copia de Eaglercraft que llama a su relay, o un
     clon de Friv que carga GameDistribution). Si además parecen juego se agregan aunque los haya
     visto un solo colegio; si no, quedan pendientes en el panel con esa señal, salvo que sean
     sitios muy visitados (top 100.000 de Tranco): una copia de un juego nunca lo es.
  6. Informa al hub qué agregó y qué quedó pendiente.

Nunca agrega dominios de la lista de permitidos ni los descartados en el panel.

PRIVACIDAD: este repositorio y sus logs de Actions son públicos. El script solo imprime
cantidades; los dominios pendientes y los reportes nunca se escriben en el log ni en el repo.

Variables de entorno: HUB_URL (p. ej. https://escolarapp-hub-api....workers.dev) y
HUB_AUDIT_TOKEN.
"""
import argparse
import io
import json
import os
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts.adguard_review import (classify_candidates, covered, is_whitelisted, merge_reports,  # noqa: E402
                                    publish, read_blocklist, whitelist)
from scripts.validate_blocklist import SHARED_SUFFIXES  # noqa: E402


def hub(method, path, body=None):
    url = os.environ["HUB_URL"].rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + os.environ["HUB_AUDIT_TOKEN"])
    # Cloudflare's bot protection rejects urllib's default User-Agent.
    req.add_header("User-Agent", "BlockList-school-audit/1.0 (+https://github.com/JosuhaSanhueza/BlockList)")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


# Un sitio de origen se toma en cuenta solo si, en su colegio, la mayor parte de sus consultas
# ocurre justo antes de un juego bloqueado (REFERRER_MIN_SHARE) y bastante más que el ruido de
# fondo de ese colegio (REFERRER_LIFT veces la parte de todas sus consultas que cae cerca de un
# bloqueo). Windows y Edge consultan solos dominios de la lista (p. ej. msn.com), y sin esto todo
# lo que hace Windows parece "sitio de origen".
# En un colegio con mucho ruido la exigencia sube hasta REFERRER_MAX_SHARE, para que una señal
# limpia (todas sus consultas cerca de un bloqueo) siga pasando.
REFERRER_MIN_SHARE = 0.5
REFERRER_MAX_SHARE = 0.9
REFERRER_LIFT = 2.0

# Una copia de un juego la abren algunos alumnos, no el laboratorio entero: se descarta lo que
# aparece en más de esta fracción de los equipos del colegio.
REFERRER_MAX_CLIENT_FRACTION = 0.5

# Nombres que no existen en internet (red local, Windows).
NON_PUBLIC_SUFFIXES = (".internal", ".null", ".local", ".lan", ".home", ".arpa", ".localdomain", ".corp")

# Los sitios de origen sin cara de juego que estén entre los más visitados del mundo no se
# proponen. Tranco es una lista pública del millón de sitios más visitados (~10 MB comprimida).
TRANCO_URL = "https://tranco-list.eu/top-1m.csv.zip"
POPULAR_TOP = 100_000

# Máximo de sitios de origen sin cara de juego que se dejan pendientes por día.
REFERRER_MAX_PENDING = 50


def item(domain, m, via=""):
    it = {"domain": domain, "queries": m.get("queries", 0), "clients": m.get("clients", 0),
          "sites": len(m["sites"]) if isinstance(m.get("sites"), set) else m.get("sites", 0)}
    if via:
        it["via"] = via
    return it


def site_referrers(report):
    """Sitios de origen de un reporte que se destacan sobre el ruido de fondo de su colegio."""
    doms = report.get("domains") or {}
    refs = report.get("referrers") or {}
    total = sum(int(v.get("queries", 0)) for v in doms.values())
    near = sum(int(v.get("queries", 0)) for v in refs.values())
    base = near / total if total else 0.0
    devices = max([int(v.get("clients", 0)) for v in list(doms.values()) + list(refs.values())] or [0])
    min_share = min(REFERRER_MAX_SHARE, max(REFERRER_MIN_SHARE, REFERRER_LIFT * base))

    out = {}
    for d, v in refs.items():
        q, c = int(v.get("queries", 0)), int(v.get("clients", 0))
        if d.endswith(NON_PUBLIC_SUFFIXES) or c > REFERRER_MAX_CLIENT_FRACTION * devices:
            continue
        share = q / max(int((doms.get(d) or {}).get("queries", 0)), q, 1)
        if share >= min_share:
            out[d] = v
    return out


def merge_referrers(reports):
    """Suma los sitios de origen destacados de varios reportes, como merge_reports."""
    merged = {}
    for r in reports:
        site = r.get("site", "?")
        for d, s in site_referrers(r).items():
            m = merged.setdefault(d, {"queries": 0, "clients": 0, "sites": set()})
            m["queries"] += int(s.get("queries", 0))
            m["clients"] += int(s.get("clients", 0))
            m["sites"].add(site)
    return merged


def referrer_candidates(refs, eligible, min_clients=2, limit=300):
    """Sitios de origen elegibles, ordenados por señal. Devuelve (dominio, stats)."""
    out = [(d, r) for d, r in refs.items() if eligible(d) and r["clients"] >= min_clients]
    out.sort(key=lambda kv: (-len(kv[1]["sites"]), -kv[1]["clients"], -kv[1]["queries"], kv[0]))
    return out[:limit]


def load_popular(top=POPULAR_TOP):
    """Los `top` dominios más visitados según Tranco, o None si no se pudo descargar la lista."""
    try:
        req = urllib.request.Request(TRANCO_URL, headers={"User-Agent": "BlockList-school-audit/1.0"})
        with urllib.request.urlopen(req, timeout=120) as r:
            z = zipfile.ZipFile(io.BytesIO(r.read()))
        popular = set()
        with z.open(z.namelist()[0]) as f:
            for line in io.TextIOWrapper(f, encoding="utf-8"):
                popular.add(line.strip().split(",", 1)[1].lower())
                if len(popular) >= top:
                    break
        return popular
    except Exception as e:  # noqa: BLE001 - sin la lista se omite solo ese paso
        print(f"Aviso: no se pudo descargar la lista de sitios populares ({type(e).__name__})")
        return None


def decide(reports, decisions, doms, wl, exc, classify, min_queries=3, min_clients=2, max_add=30, limit=300,
           popular=frozenset()):
    """Decide qué agregar y qué dejar pendiente. classify(cands) -> lista de (dominio, stats) que son juego.

    Devuelve un dict con: add (dominios a agregar), added (items para el hub), pending (items)
    y applied (aprobados del panel que se agregan). Ignora cualquier regla manual que traiga un
    reporte antiguo. popular son los sitios más visitados, que nunca se proponen como sitio de
    origen sin cara de juego; None (lista no disponible) no propone ninguno de esos.
    """
    rejected = set(decisions.get("rejected") or [])
    merged, _ = merge_reports(reports)

    def eligible(d):
        # Los equipos con Shield < v1.1.24 reportan algo.it.com como it.com: nunca proponerlo.
        return (d not in rejected and d not in SHARED_SUFFIXES and not covered(d, doms)
                and not is_whitelisted(d, wl, exc))

    add, added, pending, applied = [], [], [], []

    def take(d, stats):
        if len(add) < max_add and d not in add:
            add.append(d)
            added.append(item(d, stats))
            return True
        return False

    # 1. Aprobados en el panel.
    for d in sorted(set(decisions.get("approved") or [])):
        if eligible(d) and take(d, merged.get(d, {"sites": 0})):
            applied.append(d)

    # 2. Sitios de origen: abiertos justo antes de un juego bloqueado. Con cara de juego se
    # agregan (dos señales independientes); sin ella quedan pendientes con la señal a la vista.
    refs = referrer_candidates(merge_referrers(reports), lambda d: eligible(d) and d not in add,
                               min_clients=min_clients, limit=limit)
    ref_games = {d for d, _ in classify(refs)}
    ref_pending = 0
    for d, r in refs:
        stats = dict(merged.get(d) or r, sites=r["sites"] | (merged.get(d) or {}).get("sites", set()))
        if d in ref_games:
            take(d, stats)
        elif popular is None or d in popular:
            continue
        elif ref_pending < REFERRER_MAX_PENDING:
            pending.append(item(d, stats, via="referrer"))
            ref_pending += 1
    seen = {d for d, _ in refs}

    # 3. Dominios no bloqueados clasificados como juego.
    cand = sorted(((d, m) for d, m in merged.items()
                   if eligible(d) and d not in add and d not in seen
                   and m["queries"] >= min_queries and m["clients"] >= min_clients),
                  key=lambda kv: (-len(kv[1]["sites"]), -kv[1]["queries"]))[:limit]
    for d, m in classify(cand):
        if len(m["sites"]) >= 2:
            take(d, m)  # Si se alcanzó el tope, vuelve a aparecer mañana.
        else:
            pending.append(item(d, m))

    return {"add": add, "added": added, "pending": pending, "applied": applied}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--days", type=int, default=1)
    p.add_argument("--max-add", type=int, default=30)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    reports = hub("GET", f"/api/v1/audit/reports?days={a.days}")["reports"]
    decisions = hub("GET", "/api/v1/audit/decisions")
    doms, path = read_blocklist()
    wl, exc = whitelist()
    original = set(doms)

    def classify(cand):
        games, _ = classify_candidates(cand, a.workers)
        return games

    popular = load_popular()
    res = decide(reports, decisions, doms, wl, exc, classify, max_add=a.max_add, popular=popular)
    # Solo cantidades: el log de este repositorio es público.
    print(f"Reportes: {len(reports)} | agregar: {len(res['add'])} | pendientes: {len(res['pending'])}")

    status = publish(sorted(res["add"]), original, path, a.dry_run, "desde los colegios")
    print("Resultado:", status.splitlines()[0] if status else "-")
    if a.dry_run or status.startswith(("REVERTIDO", "commit local")):
        if not a.dry_run:
            sys.exit(1)
        return

    hub("POST", "/api/v1/audit/result", {"added": res["added"], "pending": res["pending"]})
    if res["applied"]:
        hub("POST", "/api/v1/audit/applied", {"domains": res["applied"]})


if __name__ == "__main__":
    main()
