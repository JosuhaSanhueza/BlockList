#!/usr/bin/env python3
"""Cotejo diario entre AdGuard Home (local) y GamesBlockList.txt.

Dos tareas, ambas solo lectura contra AdGuard:
  --sync-custom   Compara las reglas del "filtro personalizado" de AdGuard con la lista del repo
                  y muestra las que faltan en GitHub.
  --log-review    Lee el registro de consultas, toma dominios NO bloqueados, los clasifica con
                  is_game_website() y deja una lista corta de candidatos para aprobar.
  --apply FILE    Agrega a GamesBlockList.txt los dominios (primer token de cada línea) de FILE.

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
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
BLOCKLIST = os.path.join(ROOT, "GamesBlockList.txt")
ENV_FILE = os.path.join(ROOT, "scripts", ".env.local")
LOG_DIR = os.path.join(ROOT, "scripts", "logs")

# Hosting compartido: aquí el "dominio" a bloquear es el subdominio completo.
SHARED = ("github.io", "gitlab.io", "bitbucket.io", "pages.dev", "web.app", "netlify.app",
          "vercel.app", "weebly.com", "firebaseapp.com", "itch.io", "blogspot.com",
          "wordpress.com", "wixsite.com", "cloudfront.net", "amazonaws.com", "onrender.com")
MULTI_TLD = ("co.uk", "com.br", "com.ar", "com.mx", "com.cm", "co.in", "us.com", "co.com",
             "us.org", "org.mx", "com.au", "co.jp", "com.es", "org.es", "or.id")


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
        for e in chunk:
            if parse_time(e["time"]) < cutoff:
                return entries
            entries.append(e)
        older = data.get("oldest") or chunk[-1]["time"]
    return entries


def write_blocklist(doms, path):
    with open(BLOCKLIST, "w", encoding="utf-8") as f:
        for d in sorted(doms):
            f.write(f"||{d}^\n")
        for p in path:
            f.write(p + "\n")


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
    p.add_argument("--hours", type=int, default=24)
    p.add_argument("--min-queries", type=int, default=3)
    p.add_argument("--limit", type=int, default=300)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--out")
    a = p.parse_args()
    if a.apply:
        cmd_apply(a)
    elif a.sync_custom:
        cmd_sync_custom(a)
    elif a.log_review:
        cmd_log_review(a)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
