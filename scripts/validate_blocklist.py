#!/usr/bin/env python3
import sys
import os
import re

BLOCKLIST_FILE = "GamesBlockList.txt"
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
}

# Excepciones puntuales: subdominios específicos de un dominio en WHITELIST que
# SÍ son un sitio de juegos concreto (no la plataforma compartida entera) y por
# lo tanto sí se bloquean, igual que se hace con subdominios de gitlab.io/github.io.
WHITELIST_SUBDOMAIN_EXCEPTIONS = {
    "eaglercraft.global.ssl.fastly.net",
}

def check_line(line_clean, line_num, domains_seen):
    """Valida una línea de la blocklist. Devuelve (errores, dominio_o_None).

    `domains_seen` se muta con el dominio de esta línea si es válido, para que
    el llamador pueda detectar duplicados a través de múltiples líneas.
    """
    errors = []

    if not line_clean or line_clean.startswith("#"):
        return errors, None

    # Permitir reglas de filtrado de URL / Path de AdGuard (ej: ||sites.google.com/view/totalgameinn/*$document)
    if "$document" in line_clean or "/*" in line_clean:
        if not line_clean.startswith("||"):
            errors.append(f"Línea {line_num}: Regla de Path inválida '{line_clean}'. Debe iniciar con '||'.")
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

    # 3. Validar presencia accidental de Whitelist (solo servicios no-juegos)
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
    if domain.startswith("www."):
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
