#!/bin/sh
set -eu

runtime_config_path="/usr/share/nginx/html/cortex-runtime-config.js"

require_env() {
  value="$(printenv "$1" 2>/dev/null || true)"
  if [ -z "$value" ]; then
    echo "Cortex frontend startup requires $1." >&2
    exit 1
  fi
}

escape_js() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

validate_public_url() {
  variable_name="$1"
  url_value="$2"

  case "$url_value" in
    http://*|https://*) ;;
    *)
      echo "$variable_name must be an absolute http(s) URL." >&2
      exit 1
      ;;
  esac

  remainder="${url_value#http://}"
  if [ "$remainder" = "$url_value" ]; then
    remainder="${url_value#https://}"
  fi
  host_part="${remainder%%/*}"
  path_part="${remainder#"$host_part"}"
  host_name="${host_part%%:*}"

  case "$path_part" in
    ""|"/") ;;
    *)
      echo "$variable_name must stay rooted at the host with no nested path." >&2
      exit 1
      ;;
  esac

  case "$host_name" in
    ""|localhost|127.0.0.1|::1)
      echo "$variable_name must not use localhost in packaged frontend containers." >&2
      exit 1
      ;;
    example.com|example.org|example.net|example.test|*.example.com|*.example.org|*.example.net|*.example.test)
      echo "$variable_name must be replaced with the client's real domain." >&2
      exit 1
      ;;
  esac

  case "$url_value" in
    https://*) ;;
    *)
      echo "$variable_name must use https in packaged frontend containers." >&2
      exit 1
      ;;
  esac
}

require_env CORTEX_CONSOLE_PUBLIC_URL
require_env CORTEX_QUERY_PUBLIC_URL

console_public_url="$(printenv CORTEX_CONSOLE_PUBLIC_URL)"
query_public_url="$(printenv CORTEX_QUERY_PUBLIC_URL)"

validate_public_url "CORTEX_CONSOLE_PUBLIC_URL" "$console_public_url"
validate_public_url "CORTEX_QUERY_PUBLIC_URL" "$query_public_url"

cat >"$runtime_config_path" <<EOF
window.__CORTEX_RUNTIME_CONFIG__ = Object.freeze({
  consolePublicUrl: "$(escape_js "$console_public_url")",
  queryPublicUrl: "$(escape_js "$query_public_url")"
});
EOF
