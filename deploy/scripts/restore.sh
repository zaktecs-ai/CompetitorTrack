#!/usr/bin/env bash
# restore.sh — restore a dump and decrypt the matching .env.
#
# STATUS: documented stub. Exits non-zero on purpose. Implemented in P6, where
# the restore is actually rehearsed on a throwaway volume.
#
# Intended implementation (§A12):
#
#   1. Take the dump path as an argument; refuse to run without it.
#   2. Refuse to restore over a database that still has tenants unless --force
#      is given. Restoring onto live data is how a bad day becomes a worse one.
#   3. gpg --batch --decrypt --passphrase-file "$BACKUP_PASSPHRASE_FILE" the
#      matching env-<stamp>.gpg, and STOP if it is missing: a database restored
#      without MASTER_ENCRYPTION_KEYS has permanently undecryptable tenant
#      secrets, and finding that out after the restore is too late.
#   4. docker compose -f docker-compose.yml up -d db, wait for healthy.
#   5. pg_restore --clean --if-exists -U "$POSTGRES_USER" -d "$POSTGRES_DB".
#   6. docker compose -f docker-compose.yml run --rm api alembic upgrade head
#      (a dump may predate the current migration head).
#   7. Bring the rest up and check /api/health.
set -euo pipefail

cat >&2 <<'MESSAGE'
restore.sh is not implemented yet (P1 stub; implemented and rehearsed in P6).
MESSAGE
exit 3
