#!/usr/bin/env python3
import sys
import os
import re

BLOCKLIST_FILE = "GamesBlockList.txt"
# Dominios compartidos: cada subdominio es un sitio distinto, así que se bloquea el subdominio y
# nunca el dominio completo. Son registros tipo CentralNic (it.com, us.com...), subdominios
# gratis (eu.org) y hostings/CDN (github.io, vercel.app, cloudfront.net...). Mantener en sync con
# multiTLDs y sharedHosting en escolarapp-shield/internal/home/fleetreport.go.
SHARED_SUFFIXES = {
    "it.com", "us.com", "co.com", "br.com", "cn.com", "de.com", "eu.com", "gb.com", "gb.net",
    "uk.com", "uk.net", "jpn.com", "ru.com", "sa.com", "za.com", "in.net", "mex.com", "ae.org",
    "us.org", "eu.org",
    "github.io", "gitlab.io", "bitbucket.io", "pages.dev", "vercel.app", "netlify.app", "web.app",
    "firebaseapp.com", "cloudfront.net", "amazonaws.com", "onrender.com", "weebly.com",
    "wixsite.com", "blogspot.com", "wordpress.com", "glitch.me", "surge.sh", "replit.app",
    "global.ssl.fastly.net", "freetls.fastly.net",
}

# Fastly da a cada servicio un nombre propio bajo estos sufijos (slope.global.ssl.fastly.net,
# slope.freetls.fastly.net, el mismo servicio con dos nombres): ese servicio se puede bloquear
# como un subdominio de github.io, pero nunca la infraestructura de Fastly
# (reddit.map.fastly.net, *.sni.global.fastly.net) ni el sufijo entero (2026-10-29).
FASTLY_SERVICE_SUFFIXES = ("global.ssl.fastly.net", "freetls.fastly.net")


def is_fastly_service(domain):
    """Indica si domain es el nombre de un servicio de Fastly, p. ej. slope.freetls.fastly.net."""
    return any(domain.endswith("." + s) and "." not in domain[:-len(s) - 1]
               for s in FASTLY_SERVICE_SUFFIXES)

# Dominios cuyo apex no se bloquea porque abarca servicios de sistema, así que se bloquea
# www.<dominio> (y subdominios de juegos puntuales). msn.com: g.msn.com, ntp.msn.com y
# assets.msn.com los usan Windows, OneDrive y Edge; MSN Juegos está en www.msn.com/play
# (2026-10-20).
WWW_ONLY = {"msn.com"}

# Sitios del top 10.000 de Tranco (scripts/popular_domains.txt) que SÍ son de juegos y se
# bloquean completos por decisión explícita. Cualquier otro sitio de ese top hace fallar la
# validación: suele ser infraestructura (CDN, login, buscadores) y bloquearlo rompe servicios.
POPULAR_APPROVED = {
    "epicgames.com", "steampowered.com", "steamcommunity.com", "itch.io",
    "poki.com", "crazygames.com", "playhop.com", "cardgames.io", "aternos.org",
    "gamebanana.com", "minecraft.net", "zynga.com", "runescape.com", "my.games", "newgrounds.com",
    "king.com", "jigsawplanet.com", "miniclip.com", "solitaired.com", "coolmathgames.com",
    "neal.fun", "boardgamearena.com", "gameforge.com", "nitrotype.com", "friv.com",
    "lagged.com", "ankergames.net",
    # Buscador con sección de juegos (yandex.com/games) que el DNS no puede separar: se
    # bloquea completo por decisión explícita (2026-10-19).
    "yandex.com",
    # La versión rusa, con la misma sección de juegos (yandex.ru/games): pedida explícitamente
    # (2026-11-06).
    "yandex.ru",
    # Muro colaborativo usado para publicar Eaglercraft y otros juegos subidos como archivos:
    # se bloquea completo por decisión explícita (2026-10-20).
    "padlet.com",
    # Juegos diarios de fútbol, pedido explícitamente (2026-11-04).
    "futbol11.com",
    # Roblox y su CDN: se bloquean desde la lista de juegos (no desde Servicios bloqueados) para
    # que el botón "Permitir juegos" del docente lo controle (2026-10-20).
    "roblox.com", "rbxcdn.com",
    # Pedidos explícitamente (2026-10-22): mods de juegos (CurseForge) y rankings de juegos y
    # personajes (TierMaker).
    "curseforge.com", "tiermaker.com",
    # Aprobados en el panel del auditor (2026-10-19), confirmados el 2026-10-24: Xbox (incluye
    # Xbox Cloud Gaming en el navegador) y el emulador de Android BlueStacks.
    "xbox.com", "bluestacks.com",
}


def load_ai_companions():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "AICompanionBlockList.txt")
    with open(path, encoding="utf-8") as f:
        return {l.strip()[2:-1] for l in f if l.startswith("||")}


# La IA de personajes no tiene switch, pero un sitio que también esté en la lista de juegos se
# abriría con "Permitir juegos": el DNS responde con una sola regla y puede ser la de juegos.
AI_COMPANIONS = load_ai_companions()


def load_popular():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "popular_domains.txt")
    with open(path, encoding="utf-8") as f:
        return {l.strip() for l in f if l.strip() and not l.startswith("#")}


POPULAR = load_popular()


def load_rejected():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "games_rejected.txt")
    with open(path, encoding="utf-8") as f:
        return {l.strip() for l in f if l.strip() and not l.startswith("#")}


# Revisados a mano y descartados (herramientas para desarrolladores, noticias, reseñas): la
# búsqueda diaria no los vuelve a agregar, porque is_publishable() usa esta validación.
REJECTED = load_rejected()

# La Whitelist solo protege infraestructura esencial de internet (buscadores/redes sociales), NUNCA sitios de juegos
WHITELIST = {
    "google.com", "youtube.com", "wikipedia.org", "github.com", "microsoft.com",
    "apple.com", "amazon.com", "facebook.com", "twitter.com", "instagram.com",
    "reddit.com", "linkedin.com", "twitch.tv", "discord.com", "fandom.com",
    "duckduckgo.com", "bing.com", "yahoo.com", "cloudflare.com", "startpage.com",
    "fastly.com", "fastly.net", "fastlylb.net", "kickstarter.com",
    "archive.org", "scratch.mit.edu", "cartoonnetwork.es", "cartoonnetworkhq.com",
    # Contenido 100% educativo — ver comentario en scripts/update_blocklist.py
    # Matemáticas y aula: decisión del administrador de no bloquearlos (2026-11-02). Los portales
    # disfrazados con esos nombres (Classroom 6x, copias de Cool Math) sí se bloquean.
    "mathgames.net", "mathgames.org", "math-gamesfree.com", "mathgameshub.com",
    "mathgamesfree.io", "math-games-online.com", "coolmath.com", "playcoolmath.com",
    "classroom-games.com", "classroomgames.org", "classroomgames.app", "freeschoolgames.com",
    "classroom-games.pages.dev", "classroomgames.fun", "classroomgames.net",
    "classroom-games.gitlab.io", "classroom-games.bitbucket.io", "classroomgames.bitbucket.io",
    "cool-math-games.com",
    # Ajedrez: decisión del administrador de no bloquearlos (2026-11-04).
    "chess.com", "lichess.org", "worldchess.com",
    "mathplayground.com", "calculalo.app", "mathsframe.co.uk", "cristic.com",
    "world-geography-games.com", "juegos-geograficos.com", "sandboxeducacion.es",
    "tablasdemultiplicar.com", "tablas-multiplicar.com", "vedoque.com",
    "velocidactil.es", "typing.com", "dibujosparacolorearte.com", "freefocusgames.com",
    "educaenvivo.com", "elbuhoboo.com", "juegosinfantilespum.com", "blockly.games",
    # Sitio propio (EscolarApp), nunca bloquear.
    "escolarapp.cl",
    # Red de Akamai (CDN de Microsoft, Apple y miles de sitios). Estaba en la lista de juegos y
    # Windows la consulta sola: bloqueaba servicios legítimos (2026-10-16).
    "edgesuite.net",
    # Infraestructura que entró por la consolidación del 2026-08-11 y se sacó el 2026-10-16:
    # login de Microsoft (Office 365/Teams), Google, reporte de errores web, motor Unity
    # (también Unity Learn), y Etsy. (yandex.com se bloquea completo desde el 2026-10-19: decisión explícita).
    "msauth.net", "googlehosted.com", "sentry.io", "unity3d.com", "etsy.com",
}

# Excepciones puntuales: subdominios específicos de un dominio en WHITELIST que
# SÍ son un sitio de juegos concreto (no la plataforma compartida entera) y por
# lo tanto sí se bloquean, igual que se hace con subdominios de gitlab.io/github.io.
WHITELIST_SUBDOMAIN_EXCEPTIONS = {
    "five-nights-at-freddys-high-school.fandom.com",
    "dailygames.discover.google.com",
    "santatracker.google.com",
    "sites.google.com",
}

def check_line(line_clean, line_num, domains_seen):
    """Valida una línea de la blocklist. Devuelve (errores, dominio_o_None).

    `domains_seen` se muta con el dominio de esta línea si es válido, para que
    el llamador pueda detectar duplicados a través de múltiples líneas.
    """
    errors = []

    if not line_clean or line_clean.startswith("#"):
        return errors, None

    # Reglas con ruta o modificadores (ej. ||sites.google.com/view/juego/*$document): AdGuard Home
    # filtra DNS y solo ve el nombre del sitio, nunca la ruta, así que no bloquean nada.
    if "/" in line_clean or "$" in line_clean:
        errors.append(f"Línea {line_num}: '{line_clean}' tiene ruta o modificadores: el DNS solo ve el "
                      f"dominio y la regla no bloquea nada. Bloqueá el dominio completo o no la agregues.")
        return errors, None

    # 1. Validar sintaxis AdGuard Home ||domain^
    if not (line_clean.startswith("||") and line_clean.endswith("^")):
        errors.append(f"Línea {line_num}: Sintaxis inválida '{line_clean}'. Debe ser '||dominio^'.")
        return errors, None

    domain = line_clean[2:-1].lower()

    # 2. Verificar duplicados
    if domain in domains_seen:
        errors.append(f"Línea {line_num}: Dominio duplicado '{domain}'.")
    domains_seen.add(domain)

    # 3. Un dominio compartido completo bloquearía miles de sitios sin relación.
    if domain in SHARED_SUFFIXES:
        errors.append(f"Línea {line_num}: CRÍTICO - Dominio compartido completo '{domain}': bloqueá el subdominio.")

    # 3. La IA de personajes va solo en su propia lista.
    if domain in AI_COMPANIONS:
        errors.append(f"Línea {line_num}: '{domain}' ya está en AICompanionBlockList.txt: en esta lista "
                      f"se abriría con \"Permitir juegos\".")

    # 3a. Un sitio muy popular casi siempre es infraestructura: requiere aprobación explícita.
    if domain in POPULAR and domain not in POPULAR_APPROVED:
        errors.append(f"Línea {line_num}: CRÍTICO - '{domain}' está en el top 10.000 de sitios: si de verdad es "
                      f"de juegos, agrégalo a POPULAR_APPROVED; si no, bloquea un subdominio.")

    # 3b. Validar presencia accidental de Whitelist (solo servicios no-juegos)
    if domain not in WHITELIST_SUBDOMAIN_EXCEPTIONS and not is_fastly_service(domain):
        if domain in WHITELIST or any(domain.endswith("." + w) for w in WHITELIST):
            errors.append(f"Línea {line_num}: CRÍTICO - Dominio infraestructura en Whitelist detectado '{domain}'.")

    # 3c. Revisado y descartado a mano.
    if domain in REJECTED:
        errors.append(f"Línea {line_num}: '{domain}' está en scripts/games_rejected.txt: se revisó y no es "
                      f"un sitio de juegos. Si cambió, sácalo de ese archivo.")

    # 4. Validar formato de caracteres de dominio
    if not re.match(r'^[a-z0-9.-]+\.[a-z]{2,10}$', domain):
        errors.append(f"Línea {line_num}: Formato de dominio no válido '{domain}'.")

    # 5. Rechazar reglas con prefijo www. — ||dominio^ ya bloquea www.dominio
    # automáticamente (y todos los demás subdominios). Una regla ||www.dominio^
    # por sí sola NO cubre el dominio raíz sin www, así que agregar el dominio
    # con www es, en el mejor caso redundante, y en el peor un hueco.
    if domain.startswith("www.") and domain[4:] not in WWW_ONLY:
        errors.append(
            f"Línea {line_num}: No uses el prefijo 'www.' — agrega '{domain[4:]}' en su lugar "
            f"(||{domain[4:]}^ ya bloquea www.{domain[4:]} automáticamente)."
        )

    return errors, domain


def validate_blocklist():
    if not os.path.exists(BLOCKLIST_FILE):
        print(f"[ERROR] Archivo {BLOCKLIST_FILE} no encontrado.")
        sys.exit(1)

    errors = []
    domains_seen = set()

    with open(BLOCKLIST_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()

    print(f"[*] Validando sintaxis e integridad de {len(lines)} reglas en {BLOCKLIST_FILE}...")

    for line_num, line in enumerate(lines, 1):
        line_errors, _ = check_line(line.strip(), line_num, domains_seen)
        errors.extend(line_errors)

    if errors:
        print("\n[!] Se encontraron los siguientes errores en la validación:")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)
    else:
        print("[+] Validaciones exitosas: Sintaxis 100% correcta, sin duplicados y Whitelist respetada.")
        sys.exit(0)

if __name__ == "__main__":
    validate_blocklist()
