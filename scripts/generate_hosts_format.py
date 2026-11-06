#!/usr/bin/env python3
"""Regenera GamesBlockList_hosts.txt a partir de GamesBlockList.txt.

Solo reformatea (sin verificar accesibilidad por red, eso lo hace
cleanup_dead_domains.py, que se corre a mano), así que es rápido y se puede
correr en cada actualización diaria sin costo de red.
"""
import os

BLOCKLIST_FILE = "GamesBlockList.txt"
HOSTS_FILE = "GamesBlockList_hosts.txt"

def main():
    if not os.path.exists(BLOCKLIST_FILE):
        print(f"[ERROR] {BLOCKLIST_FILE} no existe.")
        return

    with open(BLOCKLIST_FILE, "r", encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]

    with open(HOSTS_FILE, "w", encoding="utf-8") as f:
        f.write("# --- GamesBlockList (Formato Estándar Hosts / OPNsense Unbound) ---\n")
        for r in sorted(set(lines)):
            if not ("$document" in r or "/*" in r):
                domain = r.lstrip("|").rstrip("^")
                f.write(f"0.0.0.0 {domain}\n")

    print(f"[+] {HOSTS_FILE} regenerado a partir de {BLOCKLIST_FILE}.")

if __name__ == "__main__":
    main()
