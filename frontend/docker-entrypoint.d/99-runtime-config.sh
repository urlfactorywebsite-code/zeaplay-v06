#!/bin/sh
set -eu

RUNTIME_FILE="/usr/share/nginx/html/runtime-config.js"
PRESENCE_VALUE="${PRESENCE_URL:-}"
CHAT_VALUE="${CHAT_URL:-$PRESENCE_VALUE}"

ESCAPED_PRESENCE_VALUE=$(printf '%s' "$PRESENCE_VALUE" | sed 's/\\/\\\\/g; s/"/\\"/g')
ESCAPED_CHAT_VALUE=$(printf '%s' "$CHAT_VALUE" | sed 's/\\/\\\\/g; s/"/\\"/g')

cat > "$RUNTIME_FILE" <<EOF
window.__RUNTIME_CONFIG__ = {
  PRESENCE_URL: "${ESCAPED_PRESENCE_VALUE}",
  CHAT_URL: "${ESCAPED_CHAT_VALUE}"
};
EOF
