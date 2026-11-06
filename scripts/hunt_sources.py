#!/usr/bin/env python3
"""Fuentes de candidatos que responden desde un servidor de GitHub Actions.

DuckDuckGo responde con captcha a los servidores (2026-11-06) y crt.sh suele dar 502, así que la
búsqueda diaria casi no encontraba nada. urlscan.io y la API de GitHub sí responden. Todo lo que
devuelven es un candidato: update_blocklist.py lo verifica antes de agregarlo.
"""
import html
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130 Safari/537.36"}
TIMEOUT = 20

# Búsquedas en urlscan.io: títulos de portales de juegos de los últimos días, también en los
# hostings gratuitos donde terminan los "unblocked games". urlscan solo indexa lo que alguien
# escaneó, así que encuentra sitios en uso, no solo registrados.
URLSCAN_QUERIES = [
    'page.title:"unblocked games"',
    'page.title:unblocked AND page.title:games',
    'page.title:"classroom 6x"',
    'page.title:eaglercraft',
    'page.title:"1v1.lol"',
    'page.title:"friday night funkin"',
    'page.title:"retro bowl"',
    'page.title:"slope game"',
    'page.title:"geometry dash"',
    'page.title:"subway surfers"',
    'page.title:"cookie clicker"',
    'page.title:"io games"',
    'page.title:"juegos" AND page.title:"gratis"',
    'page.domain:github.io AND page.title:games',
    'page.domain:gitlab.io AND page.title:games',
    'page.domain:vercel.app AND page.title:games',
    'page.domain:netlify.app AND page.title:games',
    'page.domain:pages.dev AND page.title:games',
]

# Título exacto de los clones de Duck Math, que se disfrazan de página de estudio.
DUCK_QUERY = "page.title:duck"

# Temas de GitHub de repositorios de sitios de juegos; se toma su página publicada.
GITHUB_TOPICS = [
    "unblocked-games", "unblocked-games-site", "games-unblocked", "eaglercraft", "html5-games",
    "browser-games", "web-games", "game-website", "unblocked", "school-games", "fnf", "retro-bowl",
]


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or UA)
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
        return resp.read().decode("utf-8", "ignore")


def _host(url):
    """Devuelve el nombre de host de una URL o de un dominio suelto, o ''."""
    url = str(url or "").strip()
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    host = urllib.parse.urlsplit(url).hostname or ""
    return host.lower().removeprefix("www.")


def search_urlscan(queries=URLSCAN_QUERIES, days=7, key=None):
    """Devuelve los dominios de las páginas que urlscan.io escaneó con estos títulos."""
    key = key or os.environ.get("URLSCAN_API_KEY", "")
    headers = dict(UA, **({"API-Key": key} if key else {}))
    found = set()
    for q in queries:
        url = "https://urlscan.io/api/v1/search/?size=100&q=" + urllib.parse.quote(f"{q} AND date:>now-{days}d")
        try:
            data = json.loads(_get(url, headers))
        except (OSError, ValueError, urllib.error.URLError):
            continue
        found.update(_host(r.get("page", {}).get("domain")) for r in data.get("results", []))
        # Sin clave, urlscan limita las búsquedas por minuto.
        time.sleep(1 if key else 3)
    found.discard("")
    return found


def search_duck_clones(days=14, key=None):
    """Devuelve los dominios cuyo título escaneado es exactamente "duck"."""
    key = key or os.environ.get("URLSCAN_API_KEY", "")
    headers = dict(UA, **({"API-Key": key} if key else {}))
    url = "https://urlscan.io/api/v1/search/?size=100&q=" + urllib.parse.quote(f"{DUCK_QUERY} AND date:>now-{days}d")
    try:
        data = json.loads(_get(url, headers))
    except (OSError, ValueError, urllib.error.URLError):
        return set()
    return {_host(r["page"].get("domain")) for r in data.get("results", [])
            if r.get("page", {}).get("title", "").strip().lower() == "duck"} - {""}


def search_github_topics(topics=GITHUB_TOPICS, since_days=60, token=None):
    """Devuelve las páginas publicadas de repositorios con estos temas, actualizados hace poco."""
    token = token or os.environ.get("GITHUB_TOKEN", "")
    headers = dict(UA, Accept="application/vnd.github+json")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    since = time.strftime("%Y-%m-%d", time.gmtime(time.time() - since_days * 86400))
    found = set()
    for topic in topics:
        q = urllib.parse.quote(f"topic:{topic} pushed:>{since}")
        try:
            data = json.loads(_get(f"https://api.github.com/search/repositories?per_page=100&sort=updated&q={q}", headers))
        except (OSError, ValueError, urllib.error.URLError):
            continue
        for repo in data.get("items", []):
            found.add(_host(repo.get("homepage")))
            if repo.get("has_pages"):
                owner = repo.get("owner", {}).get("login", "").lower()
                name = repo.get("name", "").lower()
                found.add(f"{owner}.github.io" if name == f"{owner}.github.io" else "")
        time.sleep(0 if token else 2)
    found.discard("")
    # Las páginas de proyecto (usuario.github.io/repo) comparten nombre con el usuario: solo se
    # toman las páginas propias, que son un sitio entero.
    return {d for d in found if not d.endswith("github.com")}


def is_duck_clone(page):
    """Indica si el HTML de una portada es el disfraz de Duck Math: título "duck" y el texto de
    Quizlet como descripción."""
    title = re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)
    return bool(title) and html.unescape(title.group(1)).strip().lower() == "duck" and "quizlet" in page.lower()
