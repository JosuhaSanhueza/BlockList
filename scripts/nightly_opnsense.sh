#!/bin/sh
# Corrida nocturna autónoma en el servidor OPNsense (FreeBSD, sh). Ver scripts/NIGHTLY_OPNSENSE.md
# Uso desde cron: /ruta/BlockList/scripts/nightly_opnsense.sh
set -u
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR" || exit 1
mkdir -p scripts/logs
# Una sola corrida a la vez
LOCK=/tmp/blocklist_nightly.lock
if [ -e "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then exit 0; fi
echo $$ > "$LOCK"; trap 'rm -f "$LOCK"' EXIT
PY=$(command -v python3 || echo /usr/local/bin/python3)
"$PY" scripts/adguard_review.py --nightly >> "scripts/logs/nightly_$(date +%Y-%m).log" 2>&1
# Conserva solo 30 informes
ls -1t scripts/logs/informe_*.txt 2>/dev/null | tail -n +31 | xargs -r rm -f
