#!/usr/bin/env python3
"""Lista candidatos nuevos para las listas de anime y hentai, para la revisión semanal.

Como ai_candidates.py: las fuentes son pistas, solo se muestran sitios con señales en su título y no
se agrega nada acá.
"""
import concurrent.futures
import os
import random
import re
import sys
import urllib.error

from ai_candidates import extract_domains, fetch, is_covered, page_summary
from validate_media_lists import MEDIA_LISTS, check_domain

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REJECTED_FILE = os.path.join(ROOT, "scripts", "media_rejected.txt")

# Se revisan pocos a la semana para no gastar de más.
MAX_CANDIDATES = 40
MAX_FETCH = 400
WORKERS = 32

RAW = "https://raw.githubusercontent.com/"
SOURCES = [
    RAW + "hagezi/dns-blocklists/main/wildcard/anti.piracy-onlydomains.txt",
    RAW + "hagezi/dns-blocklists/main/wildcard/nsfw-onlydomains.txt",
    "https://blocklistproject.github.io/Lists/alt-version/porn-nl.txt",
    RAW + "fmhy/edit/main/docs/non-english.md",
]

# Solo interesan los nombres de este tema: las fuentes traen mucho más.
NAME = re.compile(r"anime|manga|manhwa|manhua|anitaku|gogoanime|aniwatch|aniwave|hentai|doujin|rule34|ecchi|hanime")

HENTAI = re.compile(r"hentai|doujin|rule ?34|ecchi|uncensored|nsfw|porn|xxx|18\+", re.I)
ANIME = re.compile(r"anime|manga|manhwa|manhua|episod|cap[ií]tulo|scan|webtoon", re.I)
# Dominios en venta, apuestas y páginas por defecto, que comparten nombre con estos sitios.
NOISE = re.compile(r"for sale|a la venta|buy this (expired )?domain|parked|hugedomains|casino|coming soon", re.I)


def classify(title, desc):
    """Devuelve una pista de la lista que corresponde: hentai, anime o None."""
    text = f"{title} {desc}"
    if NOISE.search(text):
        return None
    if HENTAI.search(text):
        return "hentai"
    if ANIME.search(text):
        return "anime"
    return None


def load_known():
    """Devuelve lo que ya está en las listas o ya se descartó."""
    known = set()
    for name in MEDIA_LISTS:
        with open(os.path.join(ROOT, name), encoding="utf-8") as f:
            known.update(l.strip()[2:-1] for l in f if l.startswith("||"))
    if os.path.exists(REJECTED_FILE):
        with open(REJECTED_FILE, encoding="utf-8") as f:
            known.update(l.split()[0] for l in f if l.strip() and not l.startswith("#"))
    return known


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
            candidates |= {d for d in extract_domains(fetch(url, limit=40000000)) if NAME.search(d)}
        except (OSError, ValueError, urllib.error.URLError) as exc:
            print(f"[!] Fuente no disponible: {url} ({exc})", file=sys.stderr)

    known = load_known()
    # Al azar: los sitios sin señales no se guardan, y en orden siempre se visitarían los mismos.
    pending = [d for d in candidates if not is_covered(d, known)]
    pending = random.sample(pending, min(len(pending), MAX_FETCH))
    print(f"[*] {len(candidates)} dominios del tema, {len(pending)} por visitar.", file=sys.stderr)

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
