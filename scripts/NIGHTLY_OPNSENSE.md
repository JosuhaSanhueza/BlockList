# Corrida nocturna autónoma en OPNsense

Cada noche lee **solo las últimas 24 h** del registro de AdGuard (archivo local, sin API ni clave),
sube a GitHub las reglas que bloqueaste a mano, clasifica los dominios no bloqueados con
`is_game_website()` y agrega los que sean juegos. Deja un informe en `scripts/logs/informe_AAAA-MM-DD.txt`.

Límites: ≥3 consultas y ≥2 equipos distintos, nunca whitelist, máx. 30 por noche, validación
antes de publicar (si falla, revierte). Cada corrida es un commit `auto(nightly)`; para deshacer: `git revert <hash>`.
El informe guarda solo dominio + conteos, nunca IPs.

## Instalación (una vez, por SSH en 192.168.12.1)
```sh
pkg install -y python3 git
git clone git@github.com:JosuhaSanhueza/BlockList.git /root/BlockList
```
Push: crea una *deploy key* con escritura solo para este repo
(`ssh-keygen -t ed25519 -f /root/.ssh/blocklist_deploy -N ""`, súbela en GitHub → Settings → Deploy keys →
"Allow write access" y apunta `~/.ssh/config` a ella para github.com).

Prueba sin publicar (si AdGuard no se autodetecta, `ADGUARD_DIR=/ruta/con/AdGuardHome.yaml`):
```sh
cd /root/BlockList && python3 scripts/adguard_review.py --nightly --dry-run
```

## Programación (a las 03:00)
En OPNsense: *System → Settings → Cron → +*, minuto 0, hora 3, comando
`/root/BlockList/scripts/nightly_opnsense.sh` (o, si no aparece como opción, una acción configd propia).
Alternativa por SSH: `crontab -e` y `0 3 * * * /root/BlockList/scripts/nightly_opnsense.sh`.

Para que AdGuard recoja la lista, deja el intervalo de actualización de filtros en 12–24 h.
