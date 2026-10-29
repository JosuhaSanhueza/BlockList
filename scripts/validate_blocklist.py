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
}

# Dominios cuyo apex no se bloquea porque abarca servicios de sistema, así que se bloquea
# www.<dominio> (y subdominios de juegos puntuales). msn.com: g.msn.com, ntp.msn.com y
# assets.msn.com los usan Windows, OneDrive y Edge; MSN Juegos está en www.msn.com/play
# (2026-10-20).
WWW_ONLY = {"msn.com"}

# Sitios del top 10.000 de Tranco (scripts/popular_domains.txt) que SÍ son de juegos y se
# bloquean completos por decisión explícita. Cualquier otro sitio de ese top hace fallar la
# validación: suele ser infraestructura (CDN, login, buscadores) y bloquearlo rompe servicios.
POPULAR_APPROVED = {
    "epicgames.com", "steampowered.com", "steamcommunity.com", "itch.io", "chess.com",
    "poki.com", "crazygames.com", "lichess.org", "playhop.com", "cardgames.io", "aternos.org",
    "gamebanana.com", "minecraft.net", "zynga.com", "runescape.com", "my.games", "newgrounds.com",
    "king.com", "jigsawplanet.com", "miniclip.com", "solitaired.com", "coolmathgames.com",
    "neal.fun", "boardgamearena.com", "gameforge.com", "nitrotype.com", "emochi.com", "friv.com",
    "lagged.com", "ankergames.net",
    # Buscador con sección de juegos (yandex.com/games) que el DNS no puede separar: se
    # bloquea completo por decisión explícita (2026-10-19).
    "yandex.com",
    # Muro colaborativo usado para publicar Eaglercraft y otros juegos subidos como archivos:
    # se bloquea completo por decisión explícita (2026-10-20).
    "padlet.com",
    # Roblox y su CDN: se bloquean desde la lista de juegos (no desde Servicios bloqueados) para
    # que el botón "Permitir juegos" del docente lo controle (2026-10-20).
    "roblox.com", "rbxcdn.com",
    # Pedidos explícitamente (2026-10-22): mods de juegos (CurseForge), rankings de juegos y
    # personajes (TierMaker) y chat de rol con IA (PolyBuzz).
    "curseforge.com", "tiermaker.com", "polybuzz.ai",
    # Aprobados en el panel del auditor (2026-10-19), confirmados el 2026-10-24: Xbox (incluye
    # Xbox Cloud Gaming en el navegador) y el emulador de Android BlueStacks.
    "xbox.com", "bluestacks.com",
}


def load_popular():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "popular_domains.txt")
    with open(path, encoding="utf-8") as f:
        return {l.strip() for l in f if l.strip() and not l.startswith("#")}


POPULAR = load_popular()

# La Whitelist solo protege infraestructura esencial de internet (buscadores/redes sociales), NUNCA sitios de juegos
WHITELIST = {
    "google.com", "youtube.com", "wikipedia.org", "github.com", "microsoft.com",
    "apple.com", "amazon.com", "facebook.com", "twitter.com", "instagram.com",
    "reddit.com", "linkedin.com", "twitch.tv", "discord.com", "fandom.com",
    "duckduckgo.com", "bing.com", "yahoo.com", "cloudflare.com", "startpage.com",
    "fastly.com", "fastly.net", "fastlylb.net", "kickstarter.com",
    "archive.org", "scratch.mit.edu", "cartoonnetwork.es", "cartoonnetworkhq.com",
    # Contenido 100% educativo — ver comentario en scripts/update_blocklist.py
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
    "eaglercraft.global.ssl.fastly.net",
    # Copias de Duck Math (juegos camuflados de matemáticas) en Fastly (2026-10-22).
    "duckmath.global.ssl.fastly.net", "duck-math-123.global.ssl.fastly.net",
    "duckmath.freetls.fastly.net",
    "duck-math.global.ssl.fastly.net", "duck-math.freetls.fastly.net",
    "edu.global.ssl.fastly.net",
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

    # 3a. Un sitio muy popular casi siempre es infraestructura: requiere aprobación explícita.
    if domain in POPULAR and domain not in POPULAR_APPROVED:
        errors.append(f"Línea {line_num}: CRÍTICO - '{domain}' está en el top 10.000 de sitios: si de verdad es "
                      f"de juegos, agrégalo a POPULAR_APPROVED; si no, bloquea un subdominio.")

    # 3b. Validar presencia accidental de Whitelist (solo servicios no-juegos)
    if domain not in WHITELIST_SUBDOMAIN_EXCEPTIONS:
        if domain in WHITELIST or any(domain.endswith("." + w) for w in WHITELIST):
            errors.append(f"Línea {line_num}: CRÍTICO - Dominio infraestructura en Whitelist detectado '{domain}'.")

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
