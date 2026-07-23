#!/usr/bin/env bash
# Daily backup for SQLite + uploads. Keep 7 days.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/offeros}"
BACKUP_DIR="${BACKUP_DIR:-/opt/offeros/backups}"
KEEP_DAYS="${KEEP_DAYS:-7}"
STAMP="$(date +%Y%m%d_%H%M%S)"
DEST="${BACKUP_DIR}/offeros_${STAMP}"

mkdir -p "${DEST}"
if [[ -f "${APP_DIR}/data/offeros_v2.db" ]]; then
  cp -a "${APP_DIR}/data/offeros_v2.db" "${DEST}/"
fi
if [[ -d "${APP_DIR}/data/uploads" ]]; then
  cp -a "${APP_DIR}/data/uploads" "${DEST}/"
fi
tar -C "${BACKUP_DIR}" -czf "${DEST}.tar.gz" "offeros_${STAMP}"
rm -rf "${DEST}"
find "${BACKUP_DIR}" -name 'offeros_*.tar.gz' -mtime "+${KEEP_DAYS}" -delete
echo "backup ok: ${DEST}.tar.gz"
