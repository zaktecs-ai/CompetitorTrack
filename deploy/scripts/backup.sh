#!/usr/bin/env bash
# backup.sh — nightly database dump plus an encrypted copy of deploy/.env.
#
# STATUS: documented stub. Exits non-zero on purpose. Implemented in P6 and
# rehearsed there together with restore.sh — an unrehearsed backup is a rumour.
#
# Intended implementation (§A12), run from host cron at 03:30:
#
#   1. Read BACKUP_DIR, BACKUP_PASSPHRASE_FILE and RCLONE_REMOTE from deploy/.env.
#   2. mkdir -p "$BACKUP_DIR" with mode 700.
#   3. docker compose -f docker-compose.yml exec -T db \
#        pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB" \
#        > "$BACKUP_DIR/ct-$(date -u +%Y%m%dT%H%M%SZ).dump"
#   4. gpg --batch --symmetric --cipher-algo AES256 \
#        --passphrase-file "$BACKUP_PASSPHRASE_FILE" \
#        --output "$BACKUP_DIR/env-<stamp>.gpg" deploy/.env
#
#      This second file is not optional. A restored database WITHOUT
#      MASTER_ENCRYPTION_KEYS has undecryptable tenant SMTP passwords and Gemini
#      keys — permanently — and without JWT_SECRET every session is invalid.
#      Keep the same passphrase offline in a password manager.
#   5. Keep the 7 most recent of each kind locally.
#   6. If RCLONE_REMOTE is set: rclone copy both files there and keep 30.
#      Zero-cost remotes: Google Drive (15 GB, no card), Cloudflare R2, Backblaze B2.
set -euo pipefail

cat >&2 <<'MESSAGE'
backup.sh is not implemented yet (P1 stub; implemented and rehearsed in P6).
There is no data worth losing yet — P1 creates only the heartbeats table — but do
not schedule this in cron until it is implemented, or cron will mail you a
failure every night.
MESSAGE
exit 3
