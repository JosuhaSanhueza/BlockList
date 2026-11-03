#!/usr/bin/env python3
"""Valida AnimeBlockList.txt y HentaiBlockList.txt, que siempre están bloqueadas."""
import os
import re
import sys

from validate_blocklist import AI_COMPANIONS, POPULAR, SHARED_SUFFIXES, WHITELIST

MEDIA_LISTS = ("AnimeBlockList.txt", "HentaiBlockList.txt")

# Sitios del top 10.000 de Tranco que sí son de anime, manga pirata o hentai, aprobados a mano.
MEDIA_POPULAR_APPROVED = {
    "anime-sama.to", "animeheaven.me", "animepahe.pw", "aniwaves.ru", "aniworld.to", "crunchyroll.com",
    "fanfox.net", "hentaivietsub.com", "jkanime.net", "komiku.org", "kumanga.com", "mangadex.org",
    "mangafire.to", "mangago.me", "manhwaweb.com", "olympusxyz.com", "weebcentral.com", "yupmanga.com",
}

# Sitios legales o de otro tipo que no van en estas listas aunque hablen de anime o manga.
MEDIA_PROTECTED = {
    "pixiv.net", "comic-walker.com", "mangabox.me", "mangadraft.com", "myanimelist.net",
    "anilist.co", "tf1.fr", "honto.jp", "mangaplus.shueisha.co.jp", "viz.com",
}


def under(domain, parents):
    """Indica si domain es uno de parents o un subdominio de alguno."""
    return any(domain == p or domain.endswith("." + p) for p in parents)


def check_domain(domain):
    """Devuelve el motivo por el que domain no puede estar en estas listas, o None."""
    if domain in SHARED_SUFFIXES:
        return "hosting compartido completo"
    if domain.startswith("www."):
        return "no uses www.: ||dominio^ ya lo cubre"
    if domain in POPULAR and domain not in MEDIA_POPULAR_APPROVED:
        return "está en el top 10.000: apruébalo en MEDIA_POPULAR_APPROVED si corresponde"
    if under(domain, WHITELIST) or under(domain, MEDIA_PROTECTED):
        return "dominio protegido"
    if domain in AI_COMPANIONS:
        return "ya está en AICompanionBlockList.txt"
    return None


def check_file(lines, seen):
    """Valida las líneas de una lista. seen se comparte para detectar duplicados entre listas."""
    errors = []
    for num, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not re.match(r"^\|\|[a-z0-9.-]+\.[a-z0-9-]{2,}\^$", line):
            errors.append(f"Línea {num}: sintaxis inválida '{line}'")
            continue
        domain = line[2:-1]
        if domain in seen:
            errors.append(f"Línea {num}: duplicado '{domain}'")
        seen.add(domain)
        reason = check_domain(domain)
        if reason:
            errors.append(f"Línea {num}: '{domain}': {reason}")
    return errors


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    errors, seen = [], set()
    for name in MEDIA_LISTS:
        with open(os.path.join(root, name), encoding="utf-8") as f:
            errors += [f"{name}: {e}" for e in check_file(f.readlines(), seen)]
    if errors:
        print("\n".join(errors))
        sys.exit(1)
    print(f"[+] Listas de anime y hentai correctas: {len(seen)} dominios.")


if __name__ == "__main__":
    main()
