#!/bin/sh
# Smoke-tests a built production frontend image (the Dockerfile's `runner`
# stage). The image is public, so it must not ship the Next.js build cache
# (it holds copies of the build-generated keys), dev dependencies or the pnpm
# store, and it must refuse to start without its own Server Actions key.
#
#   docker/frontend/verify-image.sh <image> [port]
#
# Runs every check and exits non-zero if any failed.
set -eu

IMAGE=${1:?usage: verify-image.sh <image> [port]}
PORT=${2:-3999}
NAME="verify-frontend-$$"
KEY=$(head -c 32 /dev/urandom | base64)
failures=0

pass() { echo "ok   - $*"; }
fail() {
  echo "FAIL - $*" >&2
  failures=$((failures + 1))
}
cleanup() {
  docker rm -f "$NAME-nokey" "$NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Run a shell snippet inside the image without starting the server, as root
# so that no directory is hidden from the checks.
in_image() {
  docker run --rm --user 0 --entrypoint sh "$IMAGE" -c "$1"
}

# Check that the snippet $1 finds nothing in the image: its exit status 0
# means found, 1 means absent, and anything else (docker itself failing)
# counts as a failure rather than a pass.
check_absent() {
  status=0
  in_image "$1" || status=$?
  case $status in
    0) fail "image ships $2" ;;
    1) pass "no $2" ;;
    *) fail "could not check for $2 (exit $status)" ;;
  esac
}

# Wait up to $2 seconds for container $1 to stop; print its exit code, or
# "running" if it is still up.
wait_for_exit() {
  i=0
  while [ "$i" -lt "$2" ]; do
    if [ "$(docker inspect -f '{{.State.Running}}' "$1")" = false ]; then
      docker inspect -f '{{.State.ExitCode}}' "$1"
      return
    fi
    sleep 1
    i=$((i + 1))
  done
  echo running
}

# Print the HTTP status of $1, retrying for up to $2 seconds while the
# server starts.
http_status() {
  i=0
  while [ "$i" -lt "$2" ]; do
    status=$(curl -s -o /dev/null -w '%{http_code}' "$1" || true)
    if [ "$status" != 000 ]; then
      echo "$status"
      return
    fi
    sleep 1
    i=$((i + 1))
  done
  echo 000
}

# 1. The build cache holds second copies of the build-generated keys.
check_absent 'test -e /app/.next/cache' "/app/.next/cache"

# 2. No package manager, store or dev dependencies.
check_absent 'command -v pnpm >/dev/null || exit 1' "pnpm"
check_absent 'find / -xdev -type d -path "*/pnpm/store" 2>/dev/null | grep -q .' \
  "pnpm store"
for pkg in typescript jest @playwright/test eslint; do
  check_absent "find /app -type d -path '*/node_modules/$pkg' 2>/dev/null | grep -q ." \
    "dev dependency $pkg"
done

# 3. Runs as a non-root user.
uid=$(docker run --rm --entrypoint id "$IMAGE" -u)
if [ "$uid" = 0 ]; then
  fail "image runs as root"
else
  pass "runs as uid $uid"
fi

# 4. Without NEXT_SERVER_ACTIONS_ENCRYPTION_KEY the container must exit
# non-zero rather than fall back to the key baked in at build time.
docker run -d --name "$NAME-nokey" "$IMAGE" >/dev/null
code=$(wait_for_exit "$NAME-nokey" 20)
if [ "$code" = running ] || [ "$code" = 0 ]; then
  fail "starts without NEXT_SERVER_ACTIONS_ENCRYPTION_KEY (exit: $code)"
elif docker logs "$NAME-nokey" 2>&1 | grep -q NEXT_SERVER_ACTIONS_ENCRYPTION_KEY; then
  pass "refuses to start without the key (exit $code)"
else
  fail "exits $code without the key but does not name the variable"
fi

# 5. With the key set it serves pages and the third-party notices.
docker run -d --name "$NAME" -p "127.0.0.1:$PORT:3000" \
  -e NEXT_SERVER_ACTIONS_ENCRYPTION_KEY="$KEY" "$IMAGE" >/dev/null
status=$(http_status "http://127.0.0.1:$PORT/auth/login" 60)
if [ "$status" = 200 ]; then
  pass "GET /auth/login -> 200"
else
  fail "GET /auth/login -> $status"
  docker logs "$NAME" 2>&1 | tail -20 >&2
fi
# The page renders without .next/static, so check an asset it references.
asset=$(curl -s "http://127.0.0.1:$PORT/auth/login" |
  grep -o '/_next/static/[^"]*\.js' | head -n 1 || true)
if [ -n "$asset" ] && curl -sf -o /dev/null "http://127.0.0.1:$PORT$asset"; then
  pass "GET $asset -> 200"
else
  fail "static asset not served (${asset:-none referenced})"
fi
if curl -sf "http://127.0.0.1:$PORT/third-party-notices.txt" | grep -q react-leaflet; then
  pass "GET /third-party-notices.txt lists react-leaflet"
else
  fail "GET /third-party-notices.txt does not list react-leaflet"
fi

if [ "$failures" -gt 0 ]; then
  echo "$failures check(s) failed for $IMAGE" >&2
  exit 1
fi
echo "all checks passed for $IMAGE"
