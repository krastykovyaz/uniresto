#!/usr/bin/env bash
# Nightly backup of orders.db (orders, verified emails, Luni, dish photo
# records) and the uploaded dish photos themselves. Run by the
# uniresto-backup systemd timer on the server; see scripts/systemd/.
#
# Uses sqlite3's online .backup, not cp: gunicorn may be mid-write, and a
# plain copy of a live SQLite file can be torn.
set -euo pipefail

APP_DIR="${APP_DIR:-/root/uniresto}"
# Its own folder (not shared with other projects): a second machine pulls exactly this folder, read-only
# (see scripts/pull_backups.sh).
BACKUP_DIR="${BACKUP_DIR:-/root/backups/uniresto}"
KEEP_DAYS="${KEEP_DAYS:-14}"
STAMP="$(date +%F)"

mkdir -p "$BACKUP_DIR"
# .timeout: wait up to 10 s for a busy database instead of failing the night's backup at once.
sqlite3 "$APP_DIR/orders.db" ".timeout 10000" ".backup '$BACKUP_DIR/uniresto-orders-$STAMP.db'"
sqlite3 "$BACKUP_DIR/uniresto-orders-$STAMP.db" "PRAGMA integrity_check;" | grep -qx ok
tar -czf "$BACKUP_DIR/uniresto-dish-photos-$STAMP.tar.gz" -C "$APP_DIR/static" dish_photos

find "$BACKUP_DIR" -maxdepth 1 \( -name 'uniresto-orders-*.db' -o -name 'uniresto-dish-photos-*.tar.gz' \) -mtime +"$KEEP_DAYS" -delete
