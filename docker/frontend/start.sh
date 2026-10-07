#!/bin/sh
set -e

# Every `next build` bakes a random Server Actions key into the image, and the
# published images are public. Next.js reads this variable before the baked-in
# key, so requiring it means the baked-in copy is never used.
if [ -z "${NEXT_SERVER_ACTIONS_ENCRYPTION_KEY:-}" ]; then
  echo "NEXT_SERVER_ACTIONS_ENCRYPTION_KEY is not set." >&2
  echo "Generate one with: openssl rand -base64 32" >&2
  exit 1
fi

# Start the Next.js standalone server
exec node server.js
