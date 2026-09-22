#!/usr/bin/env bash
# deploy.sh <git-sha> — build on the server, migrate, swap, verify, auto-rollback.
#
# STATUS: documented stub. It exits non-zero on purpose. P1's Definition of Done
# is the stack running from `docker compose up`, and a deploy script that has
# never run against the real server is worse than no script — it would be
# trusted. It is implemented and rehearsed in P6, together with rollback and the
# backup pair. Until then, docs/DEPLOY.md §5 lists the manual commands, which are
# exactly the steps below.
#
# Intended implementation (§A12), in order:
#
#   1. Refuse to run without a git SHA argument and without deploy/.env present.
#   2. cd to the repository root; `git fetch --all` then `git checkout <sha>`
#      (detached HEAD is fine and intentional: a deploy is a SHA, not a branch).
#   3. Tag the currently running images as :prev so rollback.sh has something to
#      return to —
#        docker image tag competitortrack-api:latest competitortrack-api:prev
#        docker image tag competitortrack-web:latest competitortrack-web:prev
#      (skip silently on the very first deploy, when :latest does not exist yet).
#   4. docker compose -f docker-compose.yml build
#   5. docker compose -f docker-compose.yml run --rm api alembic upgrade head
#      Migrations are forward-only and additive, so this is safe to run before
#      the new containers are up and safe to leave applied if step 7 rolls back.
#   6. docker compose -f docker-compose.yml up -d --remove-orphans
#   7. Poll https://${SERVER_NAME}/api/health/ready for HTTP 200, up to 90 s.
#      /api/health/ready and NOT /api/health: the scheduler may still be waiting
#      on the singleton lock while the old container drains, and that must not
#      look like a failed deploy (§A12).
#   8. On failure: exec deploy/scripts/rollback.sh and exit non-zero.
#
set -euo pipefail

cat >&2 <<'MESSAGE'
deploy.sh is not implemented yet (P1 ships it as a documented stub; P6 implements
and rehearses it).

Deploy manually for now — docs/DEPLOY.md §5:

  cd "$(git rev-parse --show-toplevel)/deploy"
  docker compose -f docker-compose.yml build
  docker compose -f docker-compose.yml run --rm api alembic upgrade head
  docker compose -f docker-compose.yml up -d --remove-orphans
  curl -fsS https://"$SERVER_NAME"/api/health/ready

MESSAGE
exit 3
