#!/usr/bin/env python3
"""Búsqueda masiva de sitios de juegos por idioma, sin agentes para la parte mecánica.

Cada idioma corre en su propio hilo y junta candidatos de tres fuentes:
  - urlscan.io: páginas escaneadas con títulos de juegos en ese idioma;
  - enlaces: los enlaces externos de las portadas de portales ya bloqueados en ese idioma;
  - nombres: combinaciones típicas ("jogos" + "de-carros" + ".com.br") que resuelven en DNS.

Después descarta lo ya cubierto o rechazado, las apuestas y los hostings completos, verifica cada
dominio con is_game_website() e is_publishable(), y escribe `dominio | título | idioma` en tres
archivos, según el título (ver classify()):
  - fuertes.txt: el título invita a jugar ("play", "jugar", "unblocked"...). En la prueba del
    2026-11-12, 1 de 45 era malo: basta con revisar una muestra.
  - debiles.txt: el título no dice que se juegue ahí. Hay juegos reales y ruido: revisar a mano.
  - marcados.txt: estudios, motores, noticias, tiendas, herramientas, juegos de palabras o
    educativos. Casi todo se descarta; revisar solo si se buscan más.
Revisar esas listas cortas, en vez de que un agente lea páginas enteras, gasta muchos menos tokens.

No modifica las listas. Uso:
  python3 scripts/multi_hunt.py --lang ru pt --out /tmp/hunt
  python3 scripts/multi_hunt.py --lang es --sources names,links --max-verify 400
"""
import argparse
import itertools
import json
import os
import random
import re
import socket
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hunt_sources  # noqa: E402
from update_blocklist import FREE_HOSTING, GAMBLING_HOST, is_game_website, is_publishable  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

# Por idioma: consultas de urlscan (títulos), cómo reconocer sus portales ya bloqueados (para
# seguir sus enlaces) y piezas para armar nombres típicos.
PROFILES = {
    "ru": {
        "urlscan": ["игры онлайн", "онлайн игры", "играть бесплатно", "браузерные игры", "флеш игры",
                    "игры для девочек", "игры для мальчиков", "мини игры", "html5 игры", "игры без регистрации"],
        "seed": re.compile(r"\.(ru|su|by|kz|ua)$|igr[aiy]|igry|flash"),
        "prefix": ["igry", "igri", "igra", "igrat", "game", "games", "flash-igry", "mini-igry"],
        "middle": ["", "-online", "online", "-onlain", "onlain", "-besplatno", "besplatno", "-dlya-devochek",
                   "-dlya-malchikov", "-gonki", "-strelyalki", "-html5", "-dlya-detey", "-dvoih"],
        "tld": ["ru", "su", "com", "net", "org", "online", "club", "info"],
    },
    "pt": {
        "urlscan": ["jogos online", "jogos grátis", "jogar grátis", "jogos de carros", "jogos de meninas",
                    "jogos friv", "jogos poki", "jogos html5", "jogos para jogar", "joga online"],
        "seed": re.compile(r"\.(br|pt)$|jog[oa]s?|joga"),
        "prefix": ["jogos", "jogo", "jogar", "friv", "click", "games"],
        "middle": ["", "online", "-online", "gratis", "-gratis", "decarros", "-de-carros", "demeninas",
                   "-de-meninas", "deluta", "-de-tiro", "detiro", "html5", "360", "friv", "dois", "2jogadores"],
        "tld": ["com.br", "com", "net", "org", "pt", "net.br", "io", "online"],
    },
    "es": {
        "urlscan": ["juegos online", "juegos gratis", "jugar gratis", "juegos de carros", "juegos friv",
                    "juegos html5", "minijuegos", "juegos para chicas", "juegos de 2 jugadores", "juega online"],
        "seed": re.compile(r"\.(es|mx|ar|cl|co|pe|ve|uy|ec)$|juego|jugar"),
        "prefix": ["juegos", "juego", "jugar", "minijuegos", "friv"],
        "middle": ["", "online", "gratis", "decarros", "dechicas", "devestir", "defutbol", "dedisparos",
                   "html5", "2jugadores", "dedos", "deaccion", "demotos"],
        "tld": ["com", "net", "org", "es", "com.mx", "com.ar", "cl", "io"],
    },
    "en": {
        "urlscan": ["unblocked games", "free online games", "play free games", "html5 games", "browser games",
                    "io games", "2 player games", "games for girls", "car games", "idle games"],
        "seed": re.compile(r"games?|play|arcade|unblock"),
        "prefix": ["play", "free", "best", "top", "fun", "cool"],
        "middle": ["games", "gamesonline", "onlinegames", "html5games", "iogames", "arcade", "unblockedgames"],
        "tld": ["com", "net", "org", "io", "online", "fun", "games"],
    },
    "fr": {
        "urlscan": ["jeux en ligne", "jeux gratuits", "jouer gratuitement", "jeux html5", "jeux de voiture",
                    "jeux de fille", "jeux pour enfants"],
        "seed": re.compile(r"\.(fr|be|ch|ca)$|jeux|jeu"),
        "prefix": ["jeux", "jeu", "jouer"], "middle": ["", "gratuits", "gratuit", "enligne", "-en-ligne", "html5"],
        "tld": ["fr", "com", "net", "org", "be"],
    },
    "de": {
        "urlscan": ["kostenlose spiele", "online spiele", "spiele kostenlos", "browserspiele", "html5 spiele"],
        "seed": re.compile(r"\.(de|at|ch)$|spiel"),
        "prefix": ["spiele", "spiel", "online-spiele"], "middle": ["", "kostenlos", "-kostenlos", "online", "-online"],
        "tld": ["de", "at", "com", "net", "org"],
    },
    "it": {
        "urlscan": ["giochi online", "giochi gratis", "giocare gratis", "giochi html5"],
        "seed": re.compile(r"\.it$|giochi|gioco"),
        "prefix": ["giochi", "gioco", "giocare"], "middle": ["", "gratis", "online", "-online", "html5"],
        "tld": ["it", "com", "net", "org"],
    },
    "pl": {
        "urlscan": ["gry online", "darmowe gry", "gry za darmo", "gry html5"],
        "seed": re.compile(r"\.pl$|gry|gra"),
        "prefix": ["gry", "gra", "graj"], "middle": ["", "online", "-online", "zadarmo", "-za-darmo", "darmowe"],
        "tld": ["pl", "com", "net", "org"],
    },
    "tr": {
        "urlscan": ["oyun oyna", "ücretsiz oyunlar", "online oyunlar", "kız oyunları"],
        "seed": re.compile(r"\.tr$|oyun"),
        "prefix": ["oyun", "oyunlar", "oyna"], "middle": ["", "oyna", "online", "-oyna", "ucretsiz"],
        "tld": ["com", "net", "org", "com.tr"],
    },
    "ja": {
        "urlscan": ["無料ゲーム", "ブラウザゲーム", "オンラインゲーム 無料", "ミニゲーム"],
        "seed": re.compile(r"\.jp$"), "prefix": ["game", "games", "geemu"], "middle": ["", "-free", "free", "online"],
        "tld": ["jp", "co.jp", "com", "net"],
    },
    "ko": {
        "urlscan": ["무료 게임", "온라인 게임", "웹게임", "미니게임"],
        "seed": re.compile(r"\.kr$"), "prefix": ["game", "games"], "middle": ["", "online", "free"],
        "tld": ["kr", "co.kr", "com", "net"],
    },
    "zh": {
        "urlscan": ["小游戏", "在线游戏", "免费游戏", "网页游戏", "h5游戏"],
        "seed": re.compile(r"\.(cn|tw|hk)$|youxi|xiaoyouxi"),
        "prefix": ["youxi", "xiaoyouxi", "h5game", "4399", "7k7k"], "middle": ["", "online", "zaixian"],
        "tld": ["com", "cn", "com.cn", "net", "tw", "com.tw"],
    },
    "vi": {
        "urlscan": ["trò chơi", "game online", "chơi game miễn phí", "game hay"],
        "seed": re.compile(r"\.vn$|trochoi|choigame"),
        "prefix": ["trochoi", "choigame", "gamevui", "game"], "middle": ["", "online", "vui", "hay"],
        "tld": ["vn", "com.vn", "com", "net"],
    },
    "th": {
        "urlscan": ["เกมออนไลน์", "เกมฟรี", "เล่นเกม"],
        "seed": re.compile(r"\.th$"), "prefix": ["game", "games", "kem"], "middle": ["", "online", "free"],
        "tld": ["co.th", "in.th", "com", "net"],
    },
    "ar": {
        "urlscan": ["العاب", "ألعاب مجانية", "العاب اون لاين", "العاب بنات"],
        "seed": re.compile(r"\.(sa|ae|eg|ma|dz)$|alaab|al3ab|3ab"),
        "prefix": ["alaab", "al3ab", "lo3ba", "games"], "middle": ["", "online", "banat", "-online"],
        "tld": ["com", "net", "org", "sa", "ae", "eg"],
    },
    "hi": {
        "urlscan": ["ऑनलाइन गेम", "मुफ्त गेम", "गेम खेलें"],
        "seed": re.compile(r"\.in$"), "prefix": ["games", "khel", "game"], "middle": ["", "online", "free"],
        "tld": ["in", "co.in", "com", "net"],
    },
    "id": {
        "urlscan": ["permainan online", "game online gratis", "main game gratis", "permainan gratis"],
        "seed": re.compile(r"\.id$|permainan|mainan"),
        "prefix": ["permainan", "maingame", "gameonline", "game"], "middle": ["", "gratis", "online", "anak"],
        "tld": ["id", "co.id", "web.id", "com", "net"],
    },
    "nl": {
        "urlscan": ["spelletjes", "gratis spelletjes", "online spellen", "spellen gratis"],
        "seed": re.compile(r"\.(nl|be)$|spel"),
        "prefix": ["spelletjes", "spellen", "spel"], "middle": ["", "online", "gratis", "-online"],
        "tld": ["nl", "be", "com", "net", "org"],
    },
    "sv": {
        "urlscan": ["gratis spel", "spela gratis", "onlinespel"],
        "seed": re.compile(r"\.(se|no|dk|fi)$|spel|spil|peli"),
        "prefix": ["spel", "spela", "spil", "pelit", "spill"], "middle": ["", "online", "gratis", "-online"],
        "tld": ["se", "no", "dk", "fi", "com", "net"],
    },
    "cs": {
        "urlscan": ["hry online", "hry zdarma", "hrát zdarma", "online hry"],
        "seed": re.compile(r"\.(cz|sk)$|hry"),
        "prefix": ["hry", "hra", "onlinehry"], "middle": ["", "online", "zdarma", "-zdarma", "zadarmo"],
        "tld": ["cz", "sk", "com", "net"],
    },
    "ro": {
        "urlscan": ["jocuri online", "jocuri gratis", "joaca gratis"],
        "seed": re.compile(r"\.ro$|jocuri"),
        "prefix": ["jocuri", "joc", "joaca"], "middle": ["", "online", "gratis", "-online", "noi"],
        "tld": ["ro", "com", "net"],
    },
    "hu": {
        "urlscan": ["ingyenes játékok", "online játékok", "játék online"],
        "seed": re.compile(r"\.hu$|jatek"),
        "prefix": ["jatekok", "jatek", "jatekos"], "middle": ["", "online", "ingyen", "-online"],
        "tld": ["hu", "com", "net"],
    },
    "el": {
        "urlscan": ["παιχνίδια", "δωρεάν παιχνίδια", "παιχνίδια online"],
        "seed": re.compile(r"\.(gr|cy)$|paixnidia|paixnidi"),
        "prefix": ["paixnidia", "paixnidi"], "middle": ["", "online", "dorean", "-online"],
        "tld": ["gr", "com", "net", "eu"],
    },
    "uk": {
        "urlscan": ["ігри онлайн", "безкоштовні ігри", "грати онлайн"],
        "seed": re.compile(r"\.(ua|kz|by)$|igry|ihry"),
        "prefix": ["ihry", "igry", "igri"], "middle": ["", "online", "-online", "bezkoshtovno"],
        "tld": ["ua", "com.ua", "in.ua", "kz", "by", "com", "net"],
    },
}

# Títulos que no son sitios de juegos jugables aunque pasen is_game_website().
NOT_A_GAME_SITE = re.compile(
    r"casino|kasino|bandar|\b4d\b|bakara|baccarat|คาสิโน|สล็อต|บาคาร่า|ক্যাসিনো|erotic|erotick|\bsex|casino|казино|ставк|слот|букмекер|aposta|cassino|\bbet\b|bingo|poker|loter|lottery|slots?\b|b[oô]nus|saque|"
    r"plataforma de jogos|r\$\s?\d|\b\d*777|guide|guia\b|^loading|"
    r"for sale|domain|parked|продается|zum verkauf|à vendre|en venta|te koop|na prodej|mc games brazil|webchat|news|noticias|notícias|новости|wiki|"
    r"download|скачать|baixar|descargar|torrent|apk|cheat|чит|steam key|"
    r"matemátic|математик|typing|mecanograf|digitação|"
    r"porn|порно|xxx|hentai", re.I)

# Clasificación del título para la revisión (classify()).
STRONG = re.compile(
    r"\bplay|jogar|jogue|jogos? (online|grátis|gratis)|jugar|juega|juegos (online|gratis)|spielen|"
    r"spiele (online|kostenlos)|jouer|jouez|jeux (en ligne|gratuits)|gioca|giochi (online|gratis)|graj|"
    r"gry (online|za darmo)|oyna|играть|игры онлайн|unblocked|free online|online games|games online|"
    r"browser ?game|html5 game|in your browser|en el navegador|no download|sin descargar|spil gratis|"
    r"spela|speel|hrajte|játssz|joacă|pelaa|free games?\b|games? for|juegos de|jogos de|jeux de|giochi di|"
    r"gry dla|игры для", re.I)
FLAGGED = re.compile(
    r"studio|engine|\bign\b|store|steam|support|official|career|museum|archive|database|emulat|"
    r"forum|communit|review|tracker|rating|moneti|\bads\b|publish|develop|sdk|template|plugin|"
    r"wordpress|blog|entertainment|software|tools?\b|maker|editor|generator|asset|"
    r"math|geograph|quiz|trivia|dictionary|word|crossword|letters|palabra|scrabble|\bai\b|"
    # Redes de herramientas en línea (fotos, mapas, gráficos) que enlazan a portales de juegos.
    r"foto|photo|bild|image|collage|\bmaps?\b|chart|diagram|\bqr\b|\bzip\b|mind ?map|mind clouds?|poster|"
    r"glitter|magazine|abandonware|log in|geoguess|funding|award-winning", re.I)


def classify(title):
    """'marcado' si el título apunta a algo que no es un sitio para jugar (o es educativo),
    'fuerte' si invita a jugar, 'debil' si no dice ninguna de las dos cosas."""
    if FLAGGED.search(title):
        return "marcado"
    return "fuerte" if STRONG.search(title) else "debil"


def load_known():
    """Dominios ya bloqueados o ya rechazados."""
    known = set()
    for name in ("GamesBlockList.txt", "AIBlockList.txt", "AICompanionBlockList.txt", "AnimeBlockList.txt",
                 "HentaiBlockList.txt"):
        with open(os.path.join(ROOT, name), encoding="utf-8") as f:
            known |= {l.strip()[2:-1] for l in f if l.startswith("||")}
    with open(os.path.join(ROOT, "scripts", "games_rejected.txt"), encoding="utf-8") as f:
        known |= {l.strip() for l in f if l.strip() and not l.startswith("#")}
    return known


def covered(domain, known):
    parts = domain.split(".")
    return any(".".join(parts[i:]) in known for i in range(len(parts) - 1))


def plausible(domain):
    """Descarta lo que nunca va en la lista antes de gastar una visita."""
    if not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,10}", domain) or GAMBLING_HOST.search(domain):
        return False
    # Plataformas de apuestas brasileñas: 389win, rali777, tufao777...
    if re.search(r"\d+\.\d+\.\d+\.\d+|sslip\.io|nip\.io|777|\dwin|win\d", domain):
        return False
    hosting = next((h for h in FREE_HOSTING if domain == h or domain.endswith("." + h)), None)
    if hosting == domain:
        return False
    # En hostings gratuitos, cuatro guiones o más suele ser una página de spam SEO.
    return not (hosting and domain[: -len(hosting) - 1].count("-") >= 4)


def from_urlscan(profile, days):
    queries = [f'page.title:"{q}"' for q in profile["urlscan"]]
    return hunt_sources.search_urlscan(queries, days=days)


def seeds_for(profile, known, limit):
    """Portales ya bloqueados de este idioma, elegidos al azar para no repetir siempre los mismos."""
    seeds = sorted(d for d in known if profile["seed"].search(d) and d.count(".") <= 2)
    return random.sample(seeds, min(limit, len(seeds)))


def from_links(seeds):
    """Enlaces externos de las portadas de estos sitios."""
    def links(seed):
        try:
            html = hunt_sources._get(f"https://{seed}/")
        except Exception:
            return set()
        hosts = {hunt_sources._host(u) for u in re.findall(r'href="(https?://[^"]+)"', html)}
        return {h for h in hosts if h and not h.endswith(seed)}

    with ThreadPoolExecutor(16) as ex:
        return set().union(*ex.map(links, seeds)) if seeds else set()


def generated_names(profile):
    for p, m, t in itertools.product(profile["prefix"], profile["middle"], profile["tld"]):
        name = f"{p}{m}".strip("-")
        if name and "--" not in name:
            yield f"{name}.{t}"


# Terminaciones donde las redes de juegos repiten su marca (play123.cz, the-west.fr...).
BRAND_TLDS = [
    "com", "net", "org", "io", "co", "me", "gg", "app", "online", "site", "fun", "games", "game", "top",
    "xyz", "pro", "vip", "lol", "uno", "club", "live", "world", "school", "cc", "to", "us", "info", "biz",
    "co.uk", "de", "fr", "es", "it", "nl", "be", "pl", "pt", "com.br", "com.mx", "com.ar", "cl", "com.co",
    "pe", "co.id", "id", "ru", "ua", "kz", "cz", "sk", "hu", "ro", "gr", "se", "no", "dk", "fi", "ee", "lt",
    "lv", "si", "hr", "rs", "bg", "tr", "com.tr", "in", "jp", "kr", "vn", "th", "ph", "my", "sg", "ae",
    "com.au", "ca", "ch", "at", "ie", "eu", "asia", "mx", "ar",
]
# Sufijos de dos niveles, para sacar la marca de un dominio (jogos.com.br -> jogos).
TWO_LEVEL = {"com.br", "co.uk", "com.mx", "com.ar", "com.tr", "co.id", "com.co", "com.ve", "com.pe",
             "co.za", "com.au", "net.br", "org.uk", "co.kr", "co.jp", "com.cn", "com.pl", "com.ua",
             "com.hr", "com.es", "in.ua", "com.tw", "com.vn", "co.th", "in.th", "co.in", "web.id"}


def brand_of(domain):
    """La marca de un dominio raíz (play123.cz -> play123), o None si es un subdominio."""
    parts = domain.split(".")
    suffix = ".".join(parts[-2:]) if ".".join(parts[-2:]) in TWO_LEVEL else parts[-1]
    rest = domain[: -len(suffix) - 1]
    return rest if rest and "." not in rest else None


def from_brands(known, min_tlds=2):
    """Las marcas que ya bloqueamos en min_tlds terminaciones o más, con las demás terminaciones
    que resuelven en DNS: las redes de juegos repiten su nombre país por país."""
    seen = {}
    for d in known:
        b = brand_of(d)
        if b:
            seen.setdefault(b, set()).add(d)
    names = [f"{b}.{t}" for b, ds in seen.items() if len(ds) >= min_tlds for t in BRAND_TLDS
             if f"{b}.{t}" not in ds]
    return resolving(names)


def resolving(names):
    def resolves(d):
        try:
            socket.gethostbyname(d)
            return d
        except OSError:
            return None

    socket.setdefaulttimeout(4)
    with ThreadPoolExecutor(64) as ex:
        return {d for d in ex.map(resolves, names) if d}


def from_names(profile):
    def resolves(d):
        try:
            socket.setdefaulttimeout(4)
            socket.gethostbyname(d)
            return d
        except OSError:
            return None

    with ThreadPoolExecutor(32) as ex:
        return {d for d in ex.map(resolves, generated_names(profile)) if d}


def title_of(domain):
    try:
        html = hunt_sources._get(f"https://{domain}/")
    except Exception:
        return ""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    return " ".join(m.group(1).split())[:100] if m else ""


def verify(domain):
    """Devuelve (domain, título) si es un sitio de juegos publicable, o None."""
    try:
        if not (is_game_website(domain) and is_publishable(domain)):
            return None
    except Exception:
        return None
    title = title_of(domain)
    if not title or NOT_A_GAME_SITE.search(title):
        return None
    return domain, title


def hunt(lang, sources, known, args):
    profile = PROFILES[lang]
    found = set()
    if "urlscan" in sources:
        found |= from_urlscan(profile, args.days)
    if "links" in sources:
        found |= from_links(seeds_for(profile, known, args.max_seeds))
    if "names" in sources:
        found |= from_names(profile)
    return verify_rounds(found, known, args)


def verify_rounds(found, known, args):
    """Verifica los candidatos y, con --hops, sigue los enlaces de los sitios recién confirmados:
    los portales de una misma red se enlazan entre sí."""
    seen, ok, n_found, n_cands = set(), [], 0, 0
    for hop in range(args.hops + 1):
        cands = sorted({d.removeprefix("www.") for d in found if d} - seen)
        seen |= set(cands)
        n_found += len(cands)
        cands = [d for d in cands if plausible(d) and not covered(d, known)][: args.max_verify]
        n_cands += len(cands)
        with ThreadPoolExecutor(args.workers) as ex:
            new = [r for r in ex.map(verify, cands) if r]
        ok += new
        if hop < args.hops and new:
            found = from_links([d for d, _ in new])
    return n_found, n_cands, ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lang", nargs="+", default=list(PROFILES), choices=list(PROFILES))
    ap.add_argument("--sources", default="urlscan,links,names")
    ap.add_argument("--out", default="hunt_out")
    ap.add_argument("--days", type=int, default=60, help="antigüedad máxima de los escaneos de urlscan")
    ap.add_argument("--max-seeds", type=int, default=150, help="portales ya bloqueados a recorrer por idioma")
    ap.add_argument("--max-verify", type=int, default=600, help="candidatos a verificar por idioma")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--hops", type=int, default=1, help="rondas extra siguiendo enlaces de los sitios confirmados")
    ap.add_argument("--brands", action="store_true",
                    help="probar las marcas que ya bloqueamos en 2+ terminaciones con otras de país")
    ap.add_argument("--extra", nargs="*", default=[],
                    help="archivos con más candidatos (el primer campo de cada línea es el dominio)")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    known = load_known()
    sources = set(args.sources.split(","))
    start = time.time()
    jobs = {lang: (lambda l=lang: hunt(l, sources, known, args)) for lang in args.lang}
    if args.brands:
        jobs["marcas"] = lambda: verify_rounds(from_brands(known), known, args)
    if args.extra:
        extra = set()
        for path in args.extra:
            with open(path, encoding="utf-8") as f:
                extra |= {l.split()[0].split("|")[0].lower() for l in f if l.strip() and not l.startswith("#")}
        extra = {d for d in extra if "." in d}
        jobs["extra"] = lambda: verify_rounds(extra, known, args)
    with ThreadPoolExecutor(len(jobs)) as ex:
        futures = {name: ex.submit(fn) for name, fn in jobs.items()}
        results = {name: f.result() for name, f in futures.items()}

    groups = {"fuerte": [], "debil": [], "marcado": []}
    seen = set()
    for lang, (n_found, n_cands, ok) in results.items():
        ok = [(d, t) for d, t in ok if d not in seen]
        seen |= {d for d, _ in ok}
        for d, t in ok:
            groups[classify(t)].append(f"{d} | {t} | {lang}\n")
        print(f"[{lang}] {n_found} encontrados, {n_cands} verificados, {len(ok)} sitios de juegos")
    for name, lines in groups.items():
        path = os.path.join(args.out, f"{name}s.txt" if name != "debil" else "debiles.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(sorted(lines))
        print(f"[*] {len(lines):5d} {name} -> {path}")
    print(f"[*] {time.time() - start:.0f} s")


if __name__ == "__main__":
    main()
