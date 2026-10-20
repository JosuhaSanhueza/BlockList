#!/usr/bin/env python3
"""Cotejo diario entre AdGuard Home (local) y GamesBlockList.txt.

Dos tareas, ambas solo lectura contra AdGuard:
  --sync-custom   Compara las reglas del "filtro personalizado" de AdGuard con la lista del repo
                  y muestra las que faltan en GitHub.
  --log-review    Lee el registro de consultas, toma dominios NO bloqueados, los clasifica con
                  is_game_website() y deja una lista corta de candidatos para aprobar.
  --apply FILE    Agrega a GamesBlockList.txt los dominios (primer token de cada línea) de FILE.
  --export        Sitio: escribe el resumen del día (dominio + conteos) en un JSON local.
  --merge DIR     Central: une los reportes JSON de DIR, clasifica una vez y publica.
  --nightly       Modo autónomo (pensado para cron en el servidor): lee solo las últimas 24 h,
                  sube reglas manuales faltantes, clasifica, agrega con límites, valida,
                  hace commit/push y deja un informe en scripts/logs/. Ver --dry-run.

En el servidor OPNsense lee directo los archivos de AdGuard (data/querylog.json y
AdGuardHome.yaml), sin API ni contraseña. Directorio: ADGUARD_DIR o autodetección.

Credenciales en scripts/.env.local (fuera de git):
  export ADGUARD_URL="http://192.168.12.1:3000"
  export ADGUARD_USER="usuario"
  export ADGUARD_PASS="clave"

Privacidad: del registro solo se guardan dominio, cantidad de consultas y cantidad de
clientes distintos. Nunca IPs ni nombres de cliente.
"""
import argparse
import base64
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
BLOCKLIST = os.path.join(ROOT, "GamesBlockList.txt")
ENV_FILE = os.path.join(ROOT, "scripts", ".env.local")
ADGUARD_DIRS = ("/usr/local/AdGuardHome", "/usr/local/bin", "/var/db/adguardhome", "/var/adguardhome",
                "/usr/local/etc/adguardhome", "/opt/AdGuardHome", "/etc/AdGuardHome")
# Códigos de "reason" del querylog.json de AdGuard: solo 0 es consulta no filtrada normal.
REASON_NOT_FILTERED = 0
LOG_DIR = os.path.join(ROOT, "scripts", "logs")

# Hosting compartido: aquí el "dominio" a bloquear es el subdominio completo.
SHARED = ("github.io", "gitlab.io", "bitbucket.io", "pages.dev", "web.app", "netlify.app",
          "vercel.app", "weebly.com", "firebaseapp.com", "itch.io", "blogspot.com",
          "wordpress.com", "wixsite.com", "cloudfront.net", "amazonaws.com", "onrender.com")
MULTI_TLD = ("co.uk", "com.br", "com.ar", "com.mx", "com.cm", "co.in", "us.com", "co.com",
             "us.org", "org.mx", "com.au", "co.jp", "com.es", "org.es", "or.id")
# Dominios compartidos tipo it.com: se reporta y bloquea el subdominio (ver validate_blocklist).
from scripts.validate_blocklist import SHARED_SUFFIXES  # noqa: E402
MULTI_TLD = MULTI_TLD + tuple(sorted(SHARED_SUFFIXES - set(MULTI_TLD)))


def load_env():
    if not os.path.exists(ENV_FILE):
        return
    for line in open(ENV_FILE, encoding="utf-8"):
        m = re.match(r'\s*(?:export\s+)?([A-Z_]+)=(["\']?)(.*?)\2\s*$', line)
        if m and m.group(1) not in os.environ:
            os.environ[m.group(1)] = m.group(3)


def api_get(path, params=None):
    base = os.environ.get("ADGUARD_URL", "http://192.168.12.1:3000").rstrip("/")
    url = base + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url)
    user, pw = os.environ.get("ADGUARD_USER", ""), os.environ.get("ADGUARD_PASS", "")
    if user:
        req.add_header("Authorization", "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode())
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def registrable(name):
    """Dominio base a bloquear: apex normal o subdominio completo en hosting compartido."""
    name = name.lower().rstrip(".")
    if name.startswith("www."):
        name = name[4:]
    labels = name.split(".")
    for s in SHARED:
        if name.endswith("." + s):
            sl = s.count(".") + 1
            return ".".join(labels[-(sl + 1):])
    for t in MULTI_TLD:
        if name.endswith("." + t):
            tl = t.count(".") + 1
            return ".".join(labels[-(tl + 1):])
    return ".".join(labels[-2:]) if len(labels) >= 2 else name


def read_blocklist():
    doms, path = set(), []
    if not os.path.exists(BLOCKLIST):
        return doms, path
    for l in open(BLOCKLIST, encoding="utf-8"):
        l = l.strip()
        if not l:
            continue
        if "/" in l[2:] or "$" in l:
            path.append(l)
        elif l.startswith("||") and l.endswith("^"):
            doms.add(l[2:-1].lower())
    return doms, path


def covered(domain, doms):
    return any(domain == d or domain.endswith("." + d) for d in doms)


def whitelist():
    from scripts.validate_blocklist import WHITELIST, WHITELIST_SUBDOMAIN_EXCEPTIONS
    return set(WHITELIST), set(WHITELIST_SUBDOMAIN_EXCEPTIONS)


def is_whitelisted(domain, wl, exc):
    if domain in exc:
        return False
    return any(domain == w or domain.endswith("." + w) for w in wl)


def parse_user_rules(rules):
    """Reglas ||dominio^ simples del filtro personalizado (ignora @@, comentarios y rutas)."""
    out = []
    for r in rules or []:
        r = r.strip()
        m = re.fullmatch(r"\|\|([a-z0-9.-]+\.[a-z]{2,})\^", r, re.I)
        if m:
            out.append(m.group(1).lower())
    return out


def extract_unblocked(entries):
    """Cuenta consultas y clientes distintos por dominio base, solo respuestas no filtradas."""
    stats = {}
    for e in entries:
        if not str(e.get("reason", "")).startswith("NotFiltered") or e.get("reason") == "NotFilteredWhiteList":
            continue
        name = (e.get("question") or {}).get("name", "")
        if not name or "." not in name or re.fullmatch(r"[\d.]+", name) or name.endswith((".arpa", ".local", ".lan")):
            continue
        d = registrable(name)
        s = stats.setdefault(d, {"queries": 0, "clients": set()})
        s["queries"] += 1
        s["clients"].add(e.get("client", ""))
    return {d: {"queries": s["queries"], "clients": len(s["clients"])} for d, s in stats.items()}


def parse_time(s):
    s = re.sub(r"(\.\d{6})\d+", r"\1", s.replace("Z", "+00:00"))
    return datetime.fromisoformat(s)


def fetch_log(hours, page=500, max_pages=400):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    entries, older = [], ""
    for _ in range(max_pages):
        params = {"limit": page, "response_status": "all"}
        if older:
            params["older_than"] = older
        data = api_get("/control/querylog", params)
        chunk = data.get("data", [])
        if not chunk:
            break
        fresh = [e for e in chunk if parse_time(e["time"]) >= cutoff]
        entries.extend(fresh)
        if not fresh:  # la API no garantiza orden estricto: cortar solo si toda la página es vieja
            return entries
        older = data.get("oldest") or chunk[-1]["time"]
    return entries


def write_blocklist(doms, path):
    with open(BLOCKLIST, "w", encoding="utf-8") as f:
        for d in sorted(doms):
            f.write(f"||{d}^\n")
        for p in path:
            f.write(p + "\n")


def find_adguard_dir():
    cands = [os.environ["ADGUARD_DIR"]] if os.environ.get("ADGUARD_DIR") else list(ADGUARD_DIRS)
    for d in cands:
        if os.path.exists(os.path.join(d, "AdGuardHome.yaml")) or os.path.exists(os.path.join(d, "data", "querylog.json")):
            return d
    return None


def parse_yaml_user_rules(text):
    """Extrae la lista user_rules de AdGuardHome.yaml sin depender de PyYAML."""
    out, inside = [], False
    for line in text.splitlines():
        st = line.strip()
        if not inside:
            if re.match(r"user_rules\s*:", st):
                inside = True
                if "[]" in st:
                    break
            continue
        if st.startswith("- "):
            v = st[2:].strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
            out.append(v)
        elif st == "" or st.startswith("#"):
            continue
        else:
            break
    return out


def read_querylog_file(path, hours):
    """Lee querylog.json (y su .1 rotado) y entrega entradas con la forma de la API."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    out = []
    for fp in (path + ".1", path):
        if not os.path.exists(fp):
            continue
        with open(fp, encoding="utf-8", errors="ignore") as f:
            for line in f:
                try:
                    e = json.loads(line)
                    t = e.get("T")
                    if not t or parse_time(t) < cutoff:
                        continue
                    res = e.get("Result") or {}
                    ok = not res.get("IsFiltered") and res.get("Reason", 0) == REASON_NOT_FILTERED
                    out.append({"reason": "NotFilteredNotFound" if ok else "Filtered",
                                "question": {"name": e.get("QH", "")},
                                "client": e.get("IP", ""), "time": t})
                except Exception:
                    continue
    return out


def load_entries(hours):
    d = find_adguard_dir()
    if d and os.path.exists(os.path.join(d, "data", "querylog.json")):
        return read_querylog_file(os.path.join(d, "data", "querylog.json"), hours), "archivo local " + d
    return fetch_log(hours), "API " + os.environ.get("ADGUARD_URL", "")


def load_custom_rules():
    d = find_adguard_dir()
    if d and os.path.exists(os.path.join(d, "AdGuardHome.yaml")):
        return parse_user_rules(parse_yaml_user_rules(open(os.path.join(d, "AdGuardHome.yaml"), encoding="utf-8").read()))
    return parse_user_rules(api_get("/control/filtering/status").get("user_rules"))


LOCAL_ONLY_FILE = os.path.join(ROOT, "scripts", "manual_local_only.txt")


def load_local_only():
    """Dominios que bloqueas a mano a propósito y NO deben ir a la lista global (el botón
    "desbloquear juegos" de GameControl no debe afectarlos)."""
    if not os.path.exists(LOCAL_ONLY_FILE):
        return set()
    return {l.split("#")[0].strip().lower() for l in open(LOCAL_ONLY_FILE, encoding="utf-8")
            if l.split("#")[0].strip()}


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def publish(new, original, path, dry_run, origin):
    """Escribe, valida, hace commit y push. Devuelve un texto de estado."""
    if not new:
        return "sin cambios"
    if dry_run:
        return f"dry-run: se agregarían {len(new)} dominios"
    backup = open(BLOCKLIST, encoding="utf-8").read()
    write_blocklist(original | set(new), path)
    v = run([sys.executable, os.path.join("scripts", "validate_blocklist.py")])
    if v.returncode != 0:
        open(BLOCKLIST, "w", encoding="utf-8").write(backup)
        return "REVERTIDO: la validación falló\n" + (v.stdout + v.stderr)[-600:]
    run([sys.executable, os.path.join("scripts", "generate_hosts_format.py")])
    run(["git", "pull", "--rebase", "--autostash", "origin", "main", "-q"])
    run(["git", "add", "-u"])
    msg = (f"auto(nightly): +{len(new)} dominios {origin} [skip ci]\n\n"
           + "\n".join(f"- {d}" for d in new))
    c = run(["git", "-c", "user.name=BlockList Nightly", "-c", "user.email=nightly@localhost",
             "commit", "-q", "-m", msg])
    p = run(["git", "push", "-q", "origin", "HEAD"]) if c.returncode == 0 else c
    h = run(["git", "rev-parse", "--short", "HEAD"]).stdout.strip()
    return (f"commit {h} publicado (revertir: git revert {h})" if p.returncode == 0
            else "commit local hecho pero el push falló: " + (p.stderr or p.stdout)[-400:])


def classify_candidates(cand, workers):
    from scripts.update_blocklist import is_game_website

    def one(item):
        try:
            return item, bool(is_game_website(item[0]))
        except Exception:
            return item, None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        return [it for it, ok in ex.map(one, cand) if ok], len(cand)


def build_export(entries, manual, site, hours, min_queries=2, top=3000):
    """Resumen anónimo del día: solo dominio + conteos (sin IPs ni nombres de equipo)."""
    stats = extract_unblocked(entries)
    keep = sorted(((d, s) for d, s in stats.items() if s["queries"] >= min_queries),
                  key=lambda kv: -kv[1]["queries"])[:top]
    return {"site": site, "date": f"{datetime.now():%Y-%m-%d}", "hours": hours,
            "domains": {d: s for d, s in keep}, "manual": sorted(set(manual))}


def merge_reports(reports):
    """Suma conteos de varios sitios. clients = suma de equipos distintos por sitio."""
    merged, manual = {}, {}
    for r in reports:
        site = r.get("site", "?")
        for d, s in (r.get("domains") or {}).items():
            m = merged.setdefault(d, {"queries": 0, "clients": 0, "sites": set()})
            m["queries"] += int(s.get("queries", 0))
            m["clients"] += int(s.get("clients", 0))
            m["sites"].add(site)
        for d in r.get("manual") or []:
            manual.setdefault(d, set()).add(site)
    return merged, manual


def cmd_export(args):
    """Escribe el resumen del día en un archivo local. La subida al buzón es un paso aparte."""
    site = os.environ.get("ADGUARD_SITE", "")
    if not site:
        sys.exit("Falta ADGUARD_SITE (identificador del colegio) en scripts/.env.local")
    entries, src = load_entries(args.hours)
    try:
        manual = load_custom_rules()
    except Exception as ex:
        print("[AVISO] reglas manuales no disponibles:", ex)
        manual = []
    payload = build_export(entries, manual, site, args.hours)
    out = args.out or os.path.join(LOG_DIR, f"export_{site}_{payload['date']}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(payload, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(entries)} consultas ({src}) -> {len(payload['domains'])} dominios, "
          f"{len(manual)} reglas manuales -> {out}")


def cmd_merge(args):
    root = args.merge
    cutoff = f"{datetime.now() - timedelta(days=args.days):%Y-%m-%d}"
    reports = []
    for dp, _, files in os.walk(root):
        for fn in files:
            if fn.endswith(".json") and fn[:-5][-10:] >= cutoff:
                try:
                    reports.append(json.load(open(os.path.join(dp, fn), encoding="utf-8")))
                except Exception:
                    pass
    lines = []

    def say(x=""):
        print(x)
        lines.append(x)

    say(f"=== Informe de fusión {datetime.now():%Y-%m-%d %H:%M} ===")
    sites = sorted({r.get("site", "?") for r in reports})
    say(f"Reportes: {len(reports)} | sitios: {', '.join(sites) or '-'}")
    doms, path = read_blocklist()
    wl, exc = whitelist()
    original = set(doms)
    merged, manual = merge_reports(reports)

    local = load_local_only()
    pend = sorted(d for d in manual if re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", d)
                  and not covered(d, doms) and not covered(d, local) and not is_whitelisted(d, wl, exc))
    added_manual = []
    if args.add_manual:
        mg, _ = classify_candidates([(d, {}) for d in pend], args.workers)
        added_manual = [d for d, _ in mg]
    for d in pend:
        say(f"  ? regla manual en {len(manual[d])} sitio/s: {d} -> " + ("agregada" if d in added_manual else "NO agregada, decide tú"))
    doms |= set(added_manual)

    cand = sorted(((d, m) for d, m in merged.items()
                   if not covered(d, doms) and not is_whitelisted(d, wl, exc)
                   and m["queries"] >= args.min_queries and m["clients"] >= args.min_clients),
                  key=lambda kv: (-len(kv[1]["sites"]), -kv[1]["queries"]))[: args.limit]
    games, n = classify_candidates(
        [(d, {"queries": m["queries"], "clients": m["clients"], "sites": len(m["sites"])}) for d, m in cand],
        args.workers)
    say(f"Evaluados: {n} | clasificados como juego: {len(games)} | descartados: {n - len(games)}")
    added_auto = []
    for d, s in games[: args.max_add]:
        added_auto.append(d)
        say(f"  + {d}  ({s['queries']} consultas, {s['clients']} equipos, {s['sites']} sitio/s)")
    for d, s in games[args.max_add:]:
        say(f"  . pendiente (tope diario): {d}")
    new = sorted(set(added_manual) | set(added_auto))
    status = publish(new, original, path, args.dry_run, "desde reportes de los colegios")
    say(f"Resultado: {len(new)} dominios nuevos | {status}")
    os.makedirs(LOG_DIR, exist_ok=True)
    out = args.out or os.path.join(LOG_DIR, f"informe_fusion_{datetime.now():%Y-%m-%d}.txt")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("Informe:", out)


def cmd_nightly(args):
    from scripts.update_blocklist import is_game_website
    lines = []

    def say(s=""):
        print(s)
        lines.append(s)

    day = f"{datetime.now():%Y-%m-%d}"
    say(f"=== Informe nocturno {datetime.now():%Y-%m-%d %H:%M} ===")
    doms, path = read_blocklist()
    wl, exc = whitelist()
    original = set(doms)
    added_manual, added_auto, skipped = [], [], []

    # 1. Reglas manuales del filtro personalizado que faltan en GitHub (decisión ya tomada por ti).
    try:
        custom = load_custom_rules()
        local = load_local_only()
        pend = [d for d in sorted(set(custom)) if not covered(d, doms) and not covered(d, local)]
        skipped += [d for d in pend if is_whitelisted(d, wl, exc)]
        pend = [d for d in pend if not is_whitelisted(d, wl, exc)]
        say(f"Reglas manuales en AdGuard: {len(custom)} | solo locales: {sum(1 for d in custom if covered(d, local))} | sin cotejar con GitHub: {len(pend)}")
        if args.add_manual:
            mg, _ = classify_candidates([(d, {}) for d in pend], args.workers)
            added_manual = [d for d, _ in mg]
        for d in pend:
            tag = "agregada" if d in added_manual else "NO agregada, decide tú (súbela o añádela a scripts/manual_local_only.txt)"
            say(f"  ? regla manual: {d} -> {tag}")
    except Exception as ex:
        say(f"[AVISO] No se pudieron leer las reglas manuales: {ex}")
    doms |= set(added_manual)

    # 2. Dominios no bloqueados del día, clasificados.
    try:
        entries, src = load_entries(args.hours)
        stats = extract_unblocked(entries)
        say(f"Consultas leídas ({src}, últimas {args.hours} h): {len(entries)} | dominios no bloqueados: {len(stats)}")
        cand = sorted(((d, s) for d, s in stats.items()
                       if not covered(d, doms) and not is_whitelisted(d, wl, exc)
                       and s["queries"] >= args.min_queries and s["clients"] >= args.min_clients),
                      key=lambda kv: -kv[1]["queries"])[: args.limit]

        def classify(item):
            try:
                return item, bool(is_game_website(item[0]))
            except Exception:
                return item, None

        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            res = list(ex.map(classify, cand))
        games = [it for it, ok in res if ok]
        say(f"Evaluados: {len(cand)} | clasificados como juego: {len(games)} | descartados: {len(cand) - len(games)}")
        for d, s in games[: args.max_add]:
            added_auto.append(d)
            say(f"  + {d}  ({s['queries']} consultas, {s['clients']} equipos)")
        for d, s in games[args.max_add:]:
            say(f"  . pendiente (tope diario): {d}  ({s['queries']} consultas)")
    except Exception as ex:
        say(f"[ERROR] No se pudo analizar el registro: {ex}")

    for d in skipped:
        say(f"  ! regla manual protegida por whitelist (no agregada): {d}")

    new = sorted(set(added_manual) | set(added_auto))
    status = publish(new, original, path, args.dry_run, "desde el registro de AdGuard")
    say(f"Resultado: {len(new)} dominios nuevos | {status}")

    os.makedirs(LOG_DIR, exist_ok=True)
    out = args.out or os.path.join(LOG_DIR, f"informe_{day}.txt")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("Informe:", out)


def cmd_sync_custom(args):
    doms, _ = read_blocklist()
    wl, exc = whitelist()
    status = api_get("/control/filtering/status")
    custom = parse_user_rules(status.get("user_rules"))
    missing = sorted({d for d in custom if not covered(d, doms)})
    ok = [d for d in missing if not is_whitelisted(d, wl, exc)]
    prot = [d for d in missing if is_whitelisted(d, wl, exc)]
    print(f"Reglas personalizadas en AdGuard: {len(custom)} | faltan en GitHub: {len(ok)}")
    for d in ok:
        print("  +", d)
    for d in prot:
        print("  ! protegido por whitelist (revisar a mano):", d)
    if args.out:
        open(args.out, "w").write("\n".join(ok) + ("\n" if ok else ""))
        print("Guardado en", args.out)


def cmd_log_review(args):
    from scripts.update_blocklist import is_game_website
    doms, _ = read_blocklist()
    wl, exc = whitelist()
    entries = fetch_log(args.hours)
    stats = extract_unblocked(entries)
    cand = {d: s for d, s in stats.items()
            if not covered(d, doms) and not is_whitelisted(d, wl, exc) and s["queries"] >= args.min_queries}
    top = sorted(cand.items(), key=lambda kv: -kv[1]["queries"])[: args.limit]
    print(f"Consultas leídas: {len(entries)} | dominios no bloqueados: {len(stats)} | a clasificar: {len(top)}")

    def classify(item):
        d, s = item
        try:
            return d, s, bool(is_game_website(d))
        except Exception:
            return d, s, None

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        results = list(ex.map(classify, top))
    games = [r for r in results if r[2]]
    os.makedirs(LOG_DIR, exist_ok=True)
    out = args.out or os.path.join(LOG_DIR, f"candidatos_{datetime.now():%Y-%m-%d}.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write("# dominio  consultas  clientes   (borra las líneas que NO quieras bloquear)\n")
        for d, s, _ in games:
            f.write(f"{d}  {s['queries']}  {s['clients']}\n")
    print(f"Candidatos a juego: {len(games)} -> {out}")


def cmd_apply(args):
    doms, path = read_blocklist()
    wl, exc = whitelist()
    new = []
    for l in open(args.apply, encoding="utf-8"):
        l = l.strip()
        if not l or l.startswith("#"):
            continue
        d = l.split()[0].lower().lstrip("|").rstrip("^")
        if re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", d) and not covered(d, doms) and not is_whitelisted(d, wl, exc):
            new.append(d)
    write_blocklist(doms | set(new), path)
    print(f"Agregados {len(new)} dominios a GamesBlockList.txt")


def main():
    load_env()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sync-custom", action="store_true")
    p.add_argument("--log-review", action="store_true")
    p.add_argument("--apply", metavar="FILE")
    p.add_argument("--nightly", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--min-clients", type=int, default=2)
    p.add_argument("--max-add", type=int, default=100)
    p.add_argument("--add-manual", action="store_true", help="subir también las reglas manuales que parezcan juegos")
    p.add_argument("--export", action="store_true")
    p.add_argument("--merge", metavar="DIR")
    p.add_argument("--days", type=int, default=1)
    p.add_argument("--hours", type=int, default=24)
    p.add_argument("--min-queries", type=int, default=3)
    p.add_argument("--limit", type=int, default=300)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--out")
    a = p.parse_args()
    if a.export:
        cmd_export(a)
    elif a.merge:
        cmd_merge(a)
    elif a.nightly:
        cmd_nightly(a)
    elif a.apply:
        cmd_apply(a)
    elif a.sync_custom:
        cmd_sync_custom(a)
    elif a.log_review:
        cmd_log_review(a)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
