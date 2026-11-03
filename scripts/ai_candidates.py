#!/usr/bin/env python3
"""Lista candidatos nuevos para las listas de IA, para que la tarea diaria los revise.

Descarga fuentes públicas, descarta lo que ya está en las listas o en ai_rejected.txt, visita cada
sitio y muestra solo los que tienen señales de IA. No agrega nada: las fuentes son pistas y cada
dominio se decide después (mismo criterio que la lista de juegos).
"""
import concurrent.futures
import html
import os
import re
import ssl
import sys
import urllib.error
import urllib.request

from validate_ai_lists import AI_LISTS, check_domain

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REJECTED_FILE = os.path.join(ROOT, "scripts", "ai_rejected.txt")

# Se revisan pocos por día para no gastar de más: el resto queda para la próxima corrida.
MAX_CANDIDATES = 60
MAX_FETCH = 600
WORKERS = 32
TIMEOUT = 10

RAW = "https://raw.githubusercontent.com/"
SOURCES = [
    RAW + "nullgen-inc/ai-blocklist/main/lists/ai.domains.txt",
    RAW + "mahseema/awesome-ai-tools/main/README.md",
    RAW + "ikaijua/Awesome-AITools/main/README.md",
    RAW + "steven2358/awesome-generative-ai/main/README.md",
    RAW + "billmei/every-chatgpt-gui/main/README.md",
    RAW + "LiLittleCat/awesome-free-chatgpt/main/README.md",
    RAW + "eudk/awesome-ai-tools/main/README.md",
    RAW + "ai-collection/ai-collection/main/README.md",
    RAW + "xtekky/gpt4free/main/README.md",
]

# Dominios que aparecen en esas fuentes como enlaces y no son candidatos.
NOISE = re.compile(
    r"(github\.(com|io)|githubusercontent|githubassets|shields\.io|youtube|youtu\.be|twitter|x\.com$"
    r"|linkedin|facebook|reddit|medium\.com|wikipedia|discord|t\.me|telegram|arxiv|npmjs|pypi"
    r"|docker|apple\.com|play\.google|imgur|producthunt|substack|readthedocs|\.gov$|\.edu$"
    r"|sourceforge|vercel\.com|netlify\.com|cloudflare)"
)

COMPANION = re.compile(
    r"ai (girlfriend|boyfriend|companion|waifu|character|roleplay|role-play|role play|sexting|sex chat"
    r"|porn|friend)|character (ai|chat)|chat with (ai )?(characters|anime|your favorite)|nsfw"
    r"|uncensored ai|roleplay|role-play|virtual (girlfriend|partner|companion)|erotic|waifu"
    r"|ai dungeon|text adventure|ai (story|stories)",
    re.I,
)
TOOL = re.compile(
    r"chat ?gpt|\bgpt\b|gpt-?[3-6]|ai chat|chat ?bot|chat ?with ai|ask ai|ai assistant|ai answer"
    r"|ai search|homework|math solver|ai tutor|essay|paraphras|humaniz|ai writ|writing assistant"
    r"|undetectable|study ai|ai study|ai notes|chat with (any )?pdf|ai (image|art|video|music|voice|song"
    r"|presentation)|image generat|video generat|music generat|text to (image|video)|ai cod",
    re.I,
)

UA = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/130 Safari/537.36",
    "Accept-Language": "en,es;q=0.8",
}


def extract_domains(text):
    """Devuelve los dominios de una fuente: enlaces de un README o líneas de una lista."""
    found = {u.lower() for u in re.findall(r"https?://([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", text)}
    found.update(l.strip().lower() for l in text.splitlines()
                 if re.fullmatch(r"[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", l.strip()))
    return {d.removeprefix("www.") for d in found if not NOISE.search(d.removeprefix("www."))}


def load_known():
    """Devuelve lo que ya está en las listas de IA o ya se descartó."""
    known = set()
    for name in AI_LISTS:
        with open(os.path.join(ROOT, name), encoding="utf-8") as f:
            known.update(l.strip()[2:-1] for l in f if l.startswith("||"))
    if os.path.exists(REJECTED_FILE):
        with open(REJECTED_FILE, encoding="utf-8") as f:
            known.update(l.split()[0] for l in f if l.strip() and not l.startswith("#"))
    return known


def is_covered(domain, known):
    """Indica si domain o alguno de sus dominios padre ya está en known."""
    parts = domain.split(".")
    return any(".".join(parts[i:]) in known for i in range(len(parts) - 1))


def page_summary(body):
    """Devuelve el título y la descripción de una página."""
    title = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
    desc = re.search(r"<meta[^>]+(?:name|property)=[\"'](?:og:)?description[\"'][^>]+content=[\"']([^\"']*)",
                     body, re.I)
    clean = lambda m: re.sub(r"\s+", " ", html.unescape(m.group(1))).strip() if m else ""
    return clean(title)[:120], clean(desc)[:160]


def classify(title, desc):
    """Devuelve una pista de la lista que corresponde: companion, tool o None."""
    text = f"{title} {desc}"
    if COMPANION.search(text):
        return "companion"
    if TOOL.search(text):
        return "tool"
    return None


def fetch(url, limit=200000):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
        return r.read(limit).decode("utf-8", "ignore")


def inspect(domain):
    """Visita domain y devuelve (dominio, pista, título, descripción), o None si no hay señales."""
    try:
        title, desc = page_summary(fetch(f"https://{domain}/"))
    except (OSError, ValueError, urllib.error.URLError):
        return None
    kind = classify(title, desc)
    return (domain, kind, title, desc) if kind else None


def main():
    candidates = set()
    for url in SOURCES:
        try:
            candidates |= extract_domains(fetch(url, limit=2000000))
        except (OSError, ValueError, urllib.error.URLError) as exc:
            print(f"[!] Fuente no disponible: {url} ({exc})", file=sys.stderr)

    known = load_known()
    pending = sorted(d for d in candidates if not is_covered(d, known))[:MAX_FETCH]
    print(f"[*] {len(candidates)} dominios en las fuentes, {len(pending)} por visitar.", file=sys.stderr)

    shown = 0
    with concurrent.futures.ThreadPoolExecutor(WORKERS) as pool:
        for res in pool.map(inspect, pending):
            if res and shown < MAX_CANDIDATES:
                domain, kind, title, desc = res
                problem = check_domain(domain)
                note = f" [REVISIÓN: {problem}]" if problem else ""
                print(f"{domain} | {kind} | {title} | {desc}{note}")
                shown += 1


if __name__ == "__main__":
    main()
