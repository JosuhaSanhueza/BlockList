#!/usr/bin/env python3
"""Valida AIBlockList.txt y AICompanionBlockList.txt.

Son listas aparte de la de juegos: aquí los sitios populares son justamente lo que se quiere
bloquear (chatgpt.com), pero cada uno se aprueba a mano y nunca se bloquea infraestructura ni una
suite que el colegio usa.
"""
import os
import re
import sys

from validate_blocklist import POPULAR, SHARED_SUFFIXES, WHITELIST

AI_LISTS = ("AIBlockList.txt", "AICompanionBlockList.txt")

# Sitios del top 10.000 de Tranco que sí son de IA y se bloquean completos.
AI_POPULAR_APPROVED = {
    "anthropic.com", "character.ai", "chatgpt.com", "claude.ai", "claude.com",
    "claudeusercontent.com", "crushon.ai", "cursor.com", "cursor.sh", "deepseek.com", "dola.com",
    "doubao.com", "elevenlabs.io", "emochi.com", "flowgpt.com", "gamma.app", "githubcopilot.com",
    "grok.com", "hf.co", "higgsfield.ai", "huggingface.co", "janitorai.com", "kimi.com",
    "kiro.dev", "lovable.dev", "manus.im", "meta.ai", "midjourney.com", "mistral.ai",
    "oaistatic.com", "oaistatsig.com", "oaiusercontent.com", "ollama.com", "openai.com",
    "opencode.ai", "openrouter.ai", "perchance.org", "perplexity.ai", "polybuzz.ai",
    "quillbot.com", "qwen.ai", "runwayml.com", "spicychat.ai", "suno.com", "talkie-ai.com",
    "x.ai", "z.ai",
}

# Subdominios de IA dentro de dominios que nunca se bloquean completos.
AI_SUBDOMAINS = {
    "gemini.google.com", "aistudio.google.com", "notebooklm.google.com", "notebook.google.com",
    "bard.google.com", "copilot.microsoft.com", "copilotstudio.microsoft.com", "sydney.bing.com",
    "copilot.github.com",
}

# Lo que el colegio usa o los profesores necesitan. m365.cloud.microsoft es Microsoft 365, y los
# detectores de IA sirven para revisar tareas. Grammarly, Canva y compañía usan IA, pero no son
# herramientas de IA: bloquearlas es una decisión aparte (2026-11-02).
AI_PROTECTED = {
    "m365.cloud.microsoft", "cloud.microsoft", "office.com", "googleapis.com", "gstatic.com",
    "githubusercontent.com", "grammarly.com", "canva.com", "capcut.com", "picsart.com",
    "pixlr.com", "speechify.com", "naturalreaders.com", "semanticscholar.org", "knowt.com",
    "quizgecko.com", "gptzero.me", "zerogpt.com", "pangram.com",
}

# Subdominios permitidos de un dominio protegido.
AI_PROTECTED_EXCEPTIONS = {
    "copilot.cloud.microsoft", "generativelanguage.googleapis.com",
    "notebooklm-pa.googleapis.com", "copilot-proxy.githubusercontent.com",
}


def under(domain, parents):
    """Indica si domain es uno de parents o un subdominio de alguno."""
    return any(domain == p or domain.endswith("." + p) for p in parents)


def check_domain(domain):
    """Devuelve el motivo por el que domain no puede estar en una lista de IA, o None."""
    if domain in SHARED_SUFFIXES:
        return "hosting compartido completo"
    if domain.startswith("www."):
        return "no uses www.: ||dominio^ ya lo cubre"
    if domain in POPULAR and domain not in AI_POPULAR_APPROVED:
        return "está en el top 10.000: apruébalo en AI_POPULAR_APPROVED si de verdad es de IA"
    if domain not in AI_SUBDOMAINS and under(domain, WHITELIST):
        return "dominio protegido: solo se bloquean los subdominios de AI_SUBDOMAINS"
    if domain not in AI_PROTECTED_EXCEPTIONS and under(domain, AI_PROTECTED):
        return "lo usa el colegio o es una decisión aparte (AI_PROTECTED)"
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
    for name in AI_LISTS:
        with open(os.path.join(root, name), encoding="utf-8") as f:
            errors += [f"{name}: {e}" for e in check_file(f.readlines(), seen)]
    if errors:
        print("\n".join(errors))
        sys.exit(1)
    print(f"[+] Listas de IA correctas: {len(seen)} dominios.")


if __name__ == "__main__":
    main()
