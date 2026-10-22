#!/usr/bin/env bash
# Runs the integration suite inside an image of the app, against throwaway Postgres, Redis and
# MinIO containers on a private network. Used by CI (.github/workflows/ci.yml) and works the
# same on a laptop:
#
#     docker build -t the-way:ci . && bash .github/scripts/integration.sh the-way:ci
#
# The suite drops the schema of whatever database it is pointed at (and refuses one not named
# *_test), so this only ever talks to the containers it starts and removes afterwards. Never
# point it at real data. Anything after the image is passed to pytest.
set -euo pipefail

IMAGE="${1:?usage: integration.sh <image> [pytest arguments]}"
shift || true
PYTEST_ARGS=("$@")
[ ${#PYTEST_ARGS[@]} -gt 0 ] || PYTEST_ARGS=(tests/integration -q -p no:cacheprovider)

RUN="tw-ci-$$"
NET="$RUN"
PG="$RUN-pg"
REDIS="$RUN-redis"
S3="$RUN-s3"
VOLUME="$RUN-s3-data"

cleanup() {
  docker rm -f "$PG" "$REDIS" "$S3" >/dev/null 2>&1 || true
  docker volume rm -f "$VOLUME" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker network create "$NET" >/dev/null
docker run -d --name "$PG" --network "$NET" \
  -e POSTGRES_USER=test -e POSTGRES_PASSWORD=test -e POSTGRES_DB=the_way_test \
  postgres:17-alpine >/dev/null
docker run -d --name "$REDIS" --network "$NET" redis:8-alpine >/dev/null
# As root with a named volume: the image's non-root user cannot write to a bind mount.
docker run -d --name "$S3" --network "$NET" --user 0 -v "$VOLUME:/data" \
  -e MINIO_ROOT_USER=testkey -e MINIO_ROOT_PASSWORD=testsecret123 -e MINIO_REGION=us-east-1 \
  cgr.dev/chainguard/minio:latest server /data --address :9090 >/dev/null

wait_for() { # <description> <command...>
  local what="$1"; shift
  for _ in $(seq 1 60); do
    if "$@" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  echo "timed out waiting for $what" >&2
  docker logs "$PG" "$REDIS" "$S3" >&2 || true
  exit 1
}

wait_for postgres docker exec "$PG" pg_isready -U test -d the_way_test
wait_for redis docker exec "$REDIS" redis-cli ping
wait_for minio docker run --rm --network "$NET" \
  -e MC_HOST_local=http://testkey:testsecret123@"$S3":9090 \
  cgr.dev/chainguard/minio-client:latest ready local
docker run --rm --network "$NET" \
  -e MC_HOST_local=http://testkey:testsecret123@"$S3":9090 \
  cgr.dev/chainguard/minio-client:latest mb --ignore-existing local/test-bucket

docker run --rm --network "$NET" \
  -e DATABASE_URL="postgresql+asyncpg://test:test@$PG:5432/the_way_test" \
  -e REDIS_URL="redis://$REDIS:6379/0" \
  -e TASKIQ_BROKER_URL="redis://$REDIS:6379/1" \
  -e TASKIQ_RESULT_BACKEND_URL="redis://$REDIS:6379/2" \
  -e CRYPTOGRAPHY_FERNET_KEY=YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE= \
  -e REQUEST_SIGNING_SECRET=test-signing-secret \
  -e 'CORS_ALLOWED_ORIGINS=["https://app.example.com","https://admin.example.com"]' \
  -e SESSION_COOKIE_SECURE=false \
  -e INVITATION_ACCEPT_URL=http://localhost:3000/accept-invite \
  -e BUCKET_NAME=test-bucket -e BUCKET_PREFIX=it -e BUCKET_REGION=us-east-1 \
  -e BUCKET_ENDPOINT="http://$S3:9090" -e BUCKET_PUBLIC_ENDPOINT="http://$S3:9090" \
  -e BUCKET_ACCESS_KEY_ID=testkey -e BUCKET_SECRET_ACCESS_KEY=testsecret123 \
  -e PUBLIC_API_URL=http://localhost:8000 \
  -e DATABASE_MIGRATE_ON_STARTUP=false \
  "$IMAGE" python -m pytest "${PYTEST_ARGS[@]}"
