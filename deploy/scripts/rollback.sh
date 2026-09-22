#!/usr/bin/env bash
# rollback.sh — return to the previously running images.
#
# STATUS: documented stub, like deploy.sh. Exits non-zero on purpose.
#
# Intended implementation (§A12):
#
#   1. Require competitortrack-api:prev and competitortrack-web:prev to exist;
#      fail loudly if they do not (there is nothing to roll back to).
#   2. Retag :prev back to :latest for both images.
#   3. docker compose -f docker-compose.yml up -d
#   4. Poll /api/health/ready and report the outcome.
#
# No database downgrade is involved, and that is by design: migrations are
# forward-only and additive (§A12), so the previous image runs against the newer
# schema. A column is therefore dropped at least one release after the code
# stopped using it — never in the same release.
set -euo pipefail

cat >&2 <<'MESSAGE'
rollback.sh is not implemented yet (P1 stub; implemented in P6).

Manual rollback:

  docker image tag competitortrack-api:prev competitortrack-api:latest
  docker image tag competitortrack-web:prev competitortrack-web:latest
  cd "$(git rev-parse --show-toplevel)/deploy" && docker compose -f docker-compose.yml up -d

MESSAGE
exit 3
