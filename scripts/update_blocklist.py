#!/usr/bin/env python3
import os
import re
import random
import socket
import json
import time
import threading
import urllib.parse
import urllib.request
import ssl
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser

# Configuración
BLOCKLIST_FILE = "GamesBlockList.txt"
KEYWORDS_FILE = "keywords.txt"
MAX_NEW_DOMAINS = 300
TIMEOUT_SECONDS = 3.0  # Timeout ágil por petición
MAX_WORKERS_SEARCH = 25  # Hilos simultáneos para buscar por palabras clave
MAX_WORKERS_VERIFY = 20  # Hilos simultáneos para inspeccionar candidatos por HTTP/HTTPS

# Gemini API (grounding con Google Search, tier gratuito) — sustituto oficial y
# soportado del scraping de motores de búsqueda. Opcional: si no hay API key
# configurada, esta fuente simplemente no se usa (no rompe nada).
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_BATCH_SIZE = 6  # keywords por request, para rendir mejor la cuota gratuita diaria

# Intervalo mínimo global (segundos) entre requests al mismo motor/servicio,
# sin importar cuántos hilos estén corriendo. Con 25 hilos disparando en paralelo
# sin esto, se bombardea a DuckDuckGo/crt.sh y activan rate-limiting casi de
# inmediato, dejando el resto del run sin resultados.
MIN_REQUEST_INTERVAL = {
    "duckduckgo": 0.7,
    "crtsh": 1.2,
    "hackertarget": 0.5,
    "gemini": 4.5,  # tier gratuito: ~15 req/min máx, nos quedamos bien debajo
}
_throttle_lock = threading.Lock()
_last_request_time = {}

def throttle(source):
    """Serializa requests a `source` para respetar MIN_REQUEST_INTERVAL globalmente."""
    interval = MIN_REQUEST_INTERVAL.get(source, 0)
    if interval <= 0:
        return
    with _throttle_lock:
        now = time.monotonic()
        wait = _last_request_time.get(source, 0) + interval - now
        if wait > 0:
            time.sleep(wait)
        _last_request_time[source] = time.monotonic()

VALID_TLDS = (
    ".com", ".net", ".org", ".io", ".games", ".online", ".fun", ".site",
    ".app", ".xyz", ".top", ".me", ".play", ".gg", ".game", ".cc", ".club",
    ".es", ".co", ".uk", ".de", ".fr", ".ru", ".br", ".us", ".win", ".ws", ".network", ".dev"
)

# Plataformas de hosting compartido donde NO debemos consolidar al apex domain
SHARED_HOSTING_PLATFORMS = (
    "gitlab.io", "github.io", "bitbucket.io", "firebaseapp.com",
    "cloudfront.net", "softgames.de", "googlehosted.com", "pages.dev",
    "42web.io"
)

# Huellas dactilares de motores de juegos JS / SDKs / Eaglercraft WebSockets / Opticraft / Canvas en código cliente
JS_GAME_FOOTPRINTS = [
    r"unitywebgl", r"phaser", r"pixi\.js", r"godot", r"construct[23]?",
    r"turbowarp", r"createjs", r"poki-sdk", r"crazygames-sdk", r"gamedistribution",
    r"playcanvas", r"cocos2d", r"game-container", r"gameframe", r"game_frame",
    r"game-iframe", r"game_canvas", r"canvas-container",
    r"eaglercraft", r"eagler", r"wss://", r"ws://", r"_eaglercraftX", r"eaglercraftX",
    r"opticraft", r"teavm", r"minecraftweb", r"webminecraft", r"stickman"
]

GAME_TEXT_INDICATORS = [
    "juego", "juegos", "game", "games", "play online", "unblocked", "free online",
    "juegos gratis", "juegos online", "juego gratis", "html5 games", "browser game",
    "eaglercraft", "minecraft 1.8", "minecraft 1.2", "eaglercraftx", "web minecraft", "opticraft",
    "minecraft server", "servidor minecraft", "server ip", "stickman"
]

# La Whitelist solo protege infraestructura esencial de internet (buscadores/redes sociales), NUNCA sitios de juegos
WHITELIST = {
    "google.com", "youtube.com", "wikipedia.org", "github.com", "microsoft.com",
    "apple.com", "amazon.com", "facebook.com", "twitter.com", "instagram.com",
    "reddit.com", "linkedin.com", "twitch.tv", "discord.com", "fandom.com",
    "duckduckgo.com", "bing.com", "yahoo.com", "cloudflare.com", "startpage.com",
    # CDNs multi-tenant: miles de sitios sin relación (Pinterest, Reddit, npm, etc.)
    # comparten esta infraestructura bajo el dominio del CDN. El sitio de juegos que
    # la usa se bloquea por SU PROPIO dominio (ej. frvr.com), nunca por el del CDN.
    "fastly.com", "fastly.net", "fastlylb.net",
    # Plataformas de crowdfunding/hosting con millones de proyectos no relacionados:
    # bloquear el dominio completo por una campaña de un juego sería colateral masivo.
    "kickstarter.com",
    # Grandes instituciones/plataformas con contenido mayormente no relacionado a
    # juegos (archivo histórico, entorno educativo de coding, cadena de TV infantil).
    # Sitios de juegos específicos alojados en subdominios propios (no estos apex)
    # se bloquean por su propio dominio, nunca por el de la institución.
    "archive.org", "scratch.mit.edu", "cartoonnetwork.es", "cartoonnetworkhq.com",
    # Contenido 100% educativo (matemáticas, geografía, mecanografía, dibujo infantil,
    # entrenamiento cognitivo/atención): decisión explícita del usuario de NO bloquear
    # juegos educativos, aunque "jueguen" mecánicas de juego. Si una página mezcla
    # contenido educativo con distracción real, se revisa a mano caso por caso — esta
    # lista es solo para sitios que son inequívocamente 100% educativos.
    "mathplayground.com", "calculalo.app", "mathsframe.co.uk", "cristic.com",
    "world-geography-games.com", "juegos-geograficos.com", "sandboxeducacion.es",
    "tablasdemultiplicar.com", "tablas-multiplicar.com", "vedoque.com",
    "velocidactil.es", "typing.com", "dibujosparacolorearte.com", "freefocusgames.com",
    "educaenvivo.com", "elbuhoboo.com", "juegosinfantilespum.com", "blockly.games",
}

# Excepciones puntuales: subdominios específicos de un dominio en WHITELIST que
# SÍ son un sitio de juegos concreto (no la plataforma compartida entera) y por
# lo tanto sí se bloquean, igual que se hace con subdominios de gitlab.io/github.io.
WHITELIST_SUBDOMAIN_EXCEPTIONS = {
    "eaglercraft.global.ssl.fastly.net",
}

# CDNs / Infraestructura crítica que NUNCA debemos bloquear al escanear iframe o CDNs embebidos
SAFE_CDN_INFRASTRUCTURE = {
    "google.com", "gstatic.com", "googleapis.com", "googletagmanager.com",
    "google-analytics.com", "github.com", "gitlab.io", "cloudflare.com",
    "cloudfront.net", "jsdelivr.net", "unpkg.com", "cdnjs.cloudflare.com",
    "schema.org", "w3.org", "fastly.com", "fastly.net", "fastlylb.net"
}

ADMIN_SUBDOMAIN_PREFIXES = (
    "mail.", "webmail.", "cpanel.", "cpcalendars.", "cpcontacts.", "jira.",
    "auth.", "authorize.", "billing.", "careers.", "blog.", "docs.", "status.",
    "autodiscover.", "admin.", "mx0.", "smtp.", "relay."
)

class MetaTitleParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.title = ""
        self.meta_text = ""

    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'title':
            self.in_title = True
        elif tag.lower() == 'meta':
            attrs_dict = {k.lower(): v.lower() for k, v in attrs if k and v}
            if attrs_dict.get('name') in ['description', 'keywords']:
                self.meta_text += " " + attrs_dict.get('content', '')

    def handle_endtag(self, tag):
        if tag.lower() == 'title':
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data

def get_root_domain(domain):
    """Saca el dominio raíz (apex domain) respetando plataformas compartidas"""
    if any(shared in domain for shared in SHARED_HOSTING_PLATFORMS):
        return domain
        
    parts = domain.split('.')
    if len(parts) <= 2:
        return domain
        
    if len(parts) >= 3 and parts[-2] in ['co', 'com', 'org', 'net', 'edu', 'gov', 'poki-gdn', 'poki-cdn'] and len(parts[-1]) <= 3:
        return '.'.join(parts[-3:])
    return '.'.join(parts[-2:])

def load_existing_domains():
    if not os.path.exists(BLOCKLIST_FILE):
        return set()
    raw_domains = set()
    with open(BLOCKLIST_FILE, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip().lower()
            if line and not line.startswith("#"):
                clean = line.lstrip("|").rstrip("^").strip()
                if clean.startswith("www."):
                    clean = clean[4:]
                raw_domains.add(clean)
    return raw_domains

def load_keywords():
    if not os.path.exists(KEYWORDS_FILE):
        return []
    with open(KEYWORDS_FILE, "r", encoding="utf-8", errors="ignore") as f:
        return [line.strip().lower() for line in f if line.strip() and not line.startswith("#")]

def clean_domain(domain):
    domain = domain.lower().strip()
    domain = re.sub(r"^https?://", "", domain)
    domain = re.sub(r"^www\.", "", domain)
    domain = domain.split("/")[0].split(":")[0]
    return domain

def generate_keyword_variations(keyword):
    variations = {keyword}
    
    if "-" in keyword:
        variations.add(keyword.replace("-", " "))
        variations.add(keyword.replace("-", ""))
    
    if "juegos" in keyword and len(keyword) > 6:
        variations.add(keyword.replace("juegos", "juegos "))
    if "games" in keyword and len(keyword) > 5:
        variations.add(keyword.replace("games", " games"))
    if "unblocked" in keyword and len(keyword) > 9:
        variations.add(keyword.replace("unblocked", "unblocked "))
        
    return [v.strip() for v in variations if v.strip()]

# --- MÓDULOS DE BÚSQUEDA ---

def fetch_with_retry(req, timeout=TIMEOUT_SECONDS, context=None, retries=2, backoff=0.6):
    """GET con reintentos y backoff exponencial + jitter, para tolerar rate-limits temporales
    de los motores de búsqueda sin bombardearlos ni fallar en el primer error transitorio."""
    last_exc = None
    for attempt in range(retries + 1):
        try:
            if context is not None:
                return urllib.request.urlopen(req, timeout=timeout, context=context)
            return urllib.request.urlopen(req, timeout=timeout)
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(backoff * (2 ** attempt) + random.uniform(0, 0.3))
    raise last_exc

def search_duckduckgo_organic(keyword):
    found = set()
    kw_variations = generate_keyword_variations(keyword)
    
    # Generar Dorks avanzados incluyendo sites.google.com, .game y .games, y
    # plataformas de hosting estático gratuito (gitlab.io, bitbucket.io, pages.dev,
    # firebaseapp.com) donde suelen terminar los sitios de "unblocked games" que
    # se agregan manualmente porque el buscador normal no los encuentra.
    queries = []
    for kv in kw_variations:
        queries.extend([
            f"{kv} juegos online",
            f"{kv} unblocked games",
            f"site:sites.google.com {kv}",
            f"site:.game {kv}",
            f"site:.games {kv}",
            f"site:.io {kv}",
            f"inurl:unblocked {kv}",
            f"site:gitlab.io {kv}",
            f"site:bitbucket.io {kv}",
            f"site:pages.dev {kv}",
            f"site:firebaseapp.com {kv}",
        ])
    
    random.shuffle(queries)
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"}

    for query_str in queries[:3]:
        query = urllib.parse.quote(query_str)
        url = f"https://html.duckduckgo.com/html/?q={query}"
        req = urllib.request.Request(url, headers=headers)
        try:
            throttle("duckduckgo")
            context = ssl.create_default_context()
            with fetch_with_retry(req, context=context) as response:
                html = response.read().decode('utf-8', errors='ignore')
                raw_urls = re.findall(r'uddg=([^&\"]+)', html)
                for u in raw_urls:
                    decoded = urllib.parse.unquote(u)
                    if decoded.startswith('http'):
                        parsed = urllib.parse.urlparse(decoded)
                        dom = clean_domain(parsed.netloc)
                        if dom and dom not in WHITELIST and not any(dom.endswith("." + w) for w in WHITELIST):
                            if any(dom.endswith(tld) for tld in VALID_TLDS):
                                found.add(dom)

                        # Si es un Google Sites de juegos, escanear la página para extraer su CDN/servidor de emulador embebido
                        if "sites.google.com" in decoded and any(term in decoded.lower() for term in ["game", "juego", "unblocked", "mario", "arcade", "play"]):
                            embedded_cdns = scan_embedded_game_cdns(decoded)
                            found.update(embedded_cdns)
        except Exception:
            pass

    return found

def scan_embedded_game_cdns(target_url):
    """Escanea una página de juegos (ej. Google Sites) para extraer y validar CDNs/servidores de emuladores embebidos"""
    found_cdns = set()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        context = ssl.create_default_context()
        req = urllib.request.Request(target_url, headers=headers)
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS, context=context) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
            urls = re.findall(r'https?://[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}[^\s\"\'<>]*', html)
            for u in urls:
                netloc = urllib.parse.urlparse(u).netloc.lower()
                clean_netloc = clean_domain(netloc)
                # Filtro de seguridad: NUNCA agregar infraestructura segura (Google Fonts, Analytics, Cloudflare JS)
                if clean_netloc and not any(safe in clean_netloc for safe in SAFE_CDN_INFRASTRUCTURE):
                    if any(dom_tld for dom_tld in VALID_TLDS if clean_netloc.endswith(dom_tld)):
                        # Verificar palabras clave de emuladores / juegos en la URL
                        if any(term in u.lower() for term in ['emulator', 'mario', 'game', 'rom', 'play', 'cdn', 'asset', 'swf', 'wasm', 'eagler']):
                            found_cdns.add(clean_netloc)
    except Exception:
        pass
    return found_cdns

def search_subdomains_dns(keyword):
    found = set()
    clean_kw = keyword.replace("-", "").replace(" ", "")
    
    tlds_to_query = [".com", ".io", ".games", ".game"]
    for tld in tlds_to_query:
        dns_url = f"https://api.hackertarget.com/hostsearch/?q={urllib.parse.quote(clean_kw)}{tld}"
        try:
            throttle("hackertarget")
            req = urllib.request.Request(dns_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
                text = resp.read().decode('utf-8', errors='ignore')
                for line in text.split('\n'):
                    if ',' in line:
                        host = line.split(',')[0].strip()
                        dom = clean_domain(host)
                        if dom and dom not in WHITELIST and any(dom.endswith(vtld) for vtld in VALID_TLDS):
                            found.add(dom)
        except Exception:
            pass
    return found

# --- MÓDULO: crt.sh (Certificate Transparency Logs, gratuito y sin API key) ---
def search_crtsh(keyword):
    """Busca en logs públicos de Certificate Transparency dominios cuyo certificado
    contenga la keyword. Encuentra sitios nuevos apenas sacan su certificado SSL,
    antes de que motores de búsqueda como Google los indexen. Sustituto gratuito
    de la Google Search API (de pago) para descubrir dominios nuevos."""
    found = set()
    clean_kw = keyword.replace(" ", "")
    if len(clean_kw) < 4:
        return found
    try:
        throttle("crtsh")
        url = f"https://crt.sh/?q=%25{urllib.parse.quote(clean_kw)}%25&output=json"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with fetch_with_retry(req, timeout=8.0, retries=1) as resp:
            data = json.loads(resp.read().decode('utf-8', errors='ignore'))
            for entry in data[:300]:
                name_value = entry.get('name_value', '')
                for line in name_value.split('\n'):
                    dom = clean_domain(line.strip().lstrip('*.'))
                    if dom and dom not in WHITELIST and not any(dom.endswith("." + w) for w in WHITELIST):
                        if any(dom.endswith(tld) for tld in VALID_TLDS):
                            found.add(dom)
    except Exception:
        pass
    return found

# Regex para extraer nombres de dominio del texto de respuesta de Gemini
_DOMAIN_TOKEN_RE = re.compile(
    r'\b([a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*'
    r'(?:' + '|'.join(re.escape(tld) for tld in VALID_TLDS) + r'))\b',
    re.IGNORECASE
)

def search_gemini_grounding(keyword_batch):
    """Usa la API de Gemini con la herramienta google_search (grounding, tier
    gratuito) como reemplazo oficial y soportado del scraping de buscadores.
    La API gratuita no expone la URL real de las fuentes citadas (solo un link
    de redirección de Google), así que se le pide al modelo texto plano con
    nombres de dominio y se extraen por regex; los inventados/caídos igual
    quedan filtrados después por la verificación de contenido real."""
    found = set()
    if not GEMINI_API_KEY:
        return found

    prompt = (
        "Busca sitios web reales de juegos online gratuitos para navegador relacionados con: "
        + ", ".join(keyword_batch)
        + ". Incluye también, si existen, sitios alojados en hosting estático gratuito "
        "(gitlab.io, bitbucket.io, pages.dev, firebaseapp.com, github.io) que suelen usar "
        "los sitios de 'juegos no bloqueados para el colegio' (school unblocked games). "
        "Responde SOLO con una lista de nombres de dominio reales y accesibles ahora mismo, "
        "uno por línea, sin explicaciones ni markdown."
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}]
    }).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY,
    }
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        throttle("gemini")
        context = ssl.create_default_context()
        with fetch_with_retry(req, timeout=15.0, context=context, retries=1) as resp:
            data = json.loads(resp.read().decode('utf-8', errors='ignore'))
            for candidate in data.get('candidates', []):
                for part in candidate.get('content', {}).get('parts', []):
                    text = part.get('text', '')
                    for match in _DOMAIN_TOKEN_RE.findall(text.lower()):
                        dom = clean_domain(match)
                        if dom and dom not in WHITELIST and not any(dom.endswith("." + w) for w in WHITELIST):
                            found.add(dom)
    except Exception:
        pass
    return found

# --- MÓDULO 4: Shodan InternetDB API (Sin requerir API Key) ---
def search_shodan_internetdb(domain):
    """Consulta la API pública libre de Shodan por la IP del dominio para detectar puertos de juegos (25565, 19132) o etiquetas 'videogame'"""
    try:
        ip = socket.gethostbyname(domain)
        shodan_url = f"https://internetdb.shodan.io/{ip}"
        req = urllib.request.Request(shodan_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode('utf-8', errors='ignore'))
            ports = data.get('ports', [])
            tags = data.get('tags', [])
            hostnames = data.get('hostnames', [])
            
            # Detectar puerto estándar de Minecraft Java (25565), Bedrock (19132) o tag videogame
            if 25565 in ports or 19132 in ports or 'videogame' in tags:
                return True, hostnames
    except Exception:
        pass
    return False, []

def process_single_keyword(kw):
    res = set()
    res.update(search_duckduckgo_organic(kw))
    res.update(search_subdomains_dns(kw))
    res.update(search_crtsh(kw))
    return res

def is_game_website(domain):
    root_dom = get_root_domain(domain)
    if domain not in WHITELIST_SUBDOMAIN_EXCEPTIONS:
        if domain in WHITELIST or root_dom in WHITELIST or any(domain.endswith("." + w) for w in WHITELIST) or any(root_dom.endswith("." + w) for w in WHITELIST):
            return False

    if any(non_game in domain for non_game in ["clinical", "medical", "appliance", "hospital", "pharma"]):
        return False

    if any(domain.startswith(prefix) for prefix in ADMIN_SUBDOMAIN_PREFIXES):
        return False

    known_game_bases = [
        "poki.com", "crazygames.com", "minijuegos.com", "y8.com", "friv.com",
        "poki-cdn.com", "poki-gdn.com", "haxball.com", "stumbleguys.com",
        "eaglercraft.win", "eaglercraft.com", "eaglercraftx.com", "opticraft.com", "webmc.com", "minelatino.com", "stickmanhookgame.org"
    ]
    for base in known_game_bases:
        if domain.endswith("." + base) or domain == base:
            if not any(admin in domain for admin in ["jira.", "admin.", "corp.", "office."]):
                return True

    # 1. Consulta Shodan InternetDB libre por puerto 25565 (Minecraft Java) / 19132 (Bedrock)
    is_mc_shodan, shodan_hosts = search_shodan_internetdb(domain)
    if is_mc_shodan:
        return True

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    for scheme in ["https://", "http://"]:
        url = f"{scheme}{domain}"
        try:
            context = ssl.create_default_context()
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS, context=context) as resp:
                content_type = resp.headers.get('Content-Type', '')
                if 'text/html' not in content_type:
                    return False
                
                html = resp.read(35000).decode('utf-8', errors='ignore')
                parser = MetaTitleParser()
                parser.feed(html)
                
                combined_metadata = f"{parser.title.lower()} {parser.meta_text.lower()}"
                html_lower = html.lower()

                has_js_footprint = any(re.search(fp, html_lower) for fp in JS_GAME_FOOTPRINTS)
                has_canvas_or_iframe = "<canvas" in html_lower or ("<iframe" in html_lower and "game" in html_lower)
                text_matches = sum(1 for indicator in GAME_TEXT_INDICATORS if indicator in combined_metadata or indicator in html_lower[:3000])

                if (has_js_footprint or has_canvas_or_iframe) and text_matches >= 1:
                    return True
                elif text_matches >= 2:
                    return True

                return False
        except Exception:
            continue
            
    return False

def verify_single_candidate(domain, existing_domains):
    root_dom = get_root_domain(domain)
    if root_dom in existing_domains or domain in existing_domains:
        return None
    
    if is_game_website(domain):
        return (domain, root_dom)
    return None

def main():
    print("[*] Cargando dominios existentes y palabras clave...")
    existing_domains = load_existing_domains()
    keywords = load_keywords()
    
    print(f"[*] Total dominios existentes (consolidados): {len(existing_domains)}")
    print(f"[*] Palabras clave a procesar: {len(keywords)}")
    
    random.shuffle(keywords)
    
    candidate_domains = set()

    if GEMINI_API_KEY:
        print("[*] GEMINI_API_KEY detectada: se usará grounding con Google Search como fuente adicional.")
    else:
        print("[*] GEMINI_API_KEY no configurada: se omite la fuente Gemini (opcional).")

    keyword_batches = [keywords[i:i + GEMINI_BATCH_SIZE] for i in range(0, len(keywords), GEMINI_BATCH_SIZE)]

    print(f"[*] Rastreando candidatos en paralelo con {MAX_WORKERS_SEARCH} hilos concurrentes...")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS_SEARCH) as executor:
        futures = {executor.submit(process_single_keyword, kw): kw for kw in keywords}
        if GEMINI_API_KEY:
            futures.update({executor.submit(search_gemini_grounding, batch): batch for batch in keyword_batches})
        for future in as_completed(futures):
            try:
                res = future.result()
                candidate_domains.update(res)
            except Exception:
                pass

    print(f"[*] Candidatos únicos totales encontrados: {len(candidate_domains)}")

    to_verify = [
        d for d in candidate_domains
        if get_root_domain(d) not in existing_domains and d not in existing_domains
    ]
    already_known = sorted(candidate_domains - set(to_verify))
    print(f"[*] Candidatos ya conocidos (descartados por estar en la lista): {len(already_known)}")
    for dom in already_known:
        print(f"    - {dom} (ya cubierto por: {get_root_domain(dom)})")
    print(f"[*] Candidatos nuevos a inspeccionar (filtrados previos): {len(to_verify)}")

    new_domains = []

    print(f"[*] Verificando contenido HTML5/JS y Shodan InternetDB en paralelo con {MAX_WORKERS_VERIFY} hilos concurrentes...")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS_VERIFY) as executor:
        future_to_dom = {executor.submit(verify_single_candidate, dom, existing_domains): dom for dom in to_verify}
        for future in as_completed(future_to_dom):
            if len(new_domains) >= MAX_NEW_DOMAINS:
                break
            dom_checked = future_to_dom[future]
            try:
                res = future.result()
                if res:
                    domain, root_dom = res
                    if root_dom not in existing_domains:
                        print(f"  [+] Confirmado sitio de juegos / Shodan MC: {domain} -> Consolidando a: {root_dom}")
                        new_domains.append(root_dom)
                        existing_domains.add(root_dom)
                    else:
                        print(f"  [-] Descartado (ya consolidado en esta corrida): {dom_checked}")
                else:
                    print(f"  [-] Descartado (no parece sitio de juegos): {dom_checked}")
            except Exception as exc:
                print(f"  [-] Descartado (error de verificación: {exc}): {dom_checked}")

    if new_domains:
        print(f"\n[+] Agregando {len(new_domains)} dominios principales consolidados a {BLOCKLIST_FILE}...")
        all_domains = sorted(list(existing_domains))
        with open(BLOCKLIST_FILE, "w", encoding="utf-8") as f:
            for dom in all_domains:
                f.write(f"||{dom}^\n")
        print(f"[+] Archivo de lista de bloqueo actualizado exitosamente con sintaxis AdGuard Home ({len(new_domains)} añadidos).")
    else:
        print("\n[-] No se encontraron nuevos dominios para agregar hoy.")

if __name__ == "__main__":
    main()
