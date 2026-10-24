#!/usr/bin/env bash
# Runs on the OFF-SITE machine (aak-third), not on the server: copies the server's nightly UniResto backups
# (orders database + dish photos) to this machine, so a lost server or disk does not take the backups with it.
#
#   crontab -e   ->   45 4 * * * /home/alex/projects/uniresto/pull_backups.sh >> /home/alex/projects/uniresto/pull.log 2>&1
#
# The server only lets this machine's key READ /root/backups/uniresto (rrsync -ro), nothing else.
# Copies are kept here for KEEP_DAYS (longer than the server's 14), then pruned.
set -euo pipefail

DEST="${DEST:-/home/alex/projects/uniresto/backups}"
KEY="${KEY:-$HOME/.ssh/uniresto_backup}"
SERVER="${SERVER:-root@resto.unilu.space}"
KEEP_DAYS="${KEEP_DAYS:-90}"

mkdir -p "$DEST"
# The remote side is rrsync, rooted at /root/backups/uniresto: "." is that folder.
rsync -a --partial -e "ssh -i $KEY -o BatchMode=yes -o StrictHostKeyChecking=accept-new" "$SERVER:." "$DEST/"
find "$DEST" -maxdepth 1 \( -name 'uniresto-orders-*.db' -o -name 'uniresto-dish-photos-*.tar.gz' \) -mtime +"$KEEP_DAYS" -delete

# A copy that is not a valid database is worse than none: check the newest one.
newest="$(ls -1t "$DEST"/uniresto-orders-*.db | head -1)"
if command -v sqlite3 >/dev/null; then
  [ "$(sqlite3 "$newest" 'PRAGMA integrity_check;')" = "ok" ] || { echo "$(date -Is) BAD COPY: $newest"; exit 2; }
fi
echo "$(date -Is) ok: $(basename "$newest")"
