#!/bin/sh
# Register the Daryafter native messaging host with Firefox / Chrome /
# Chromium, so the extension can start Daryafter when it is not running.
#
# Usage:
#   ./install.sh                      install for Firefox + Chromium + Chrome
#   ./install.sh --firefox-only       only Firefox
#   CHROME_ID=abcdef... ./install.sh  also allow this Chrome extension ID
#                                     (read it from chrome://extensions)
#
# No root needed: manifests are written into your home directory.

set -eu

here="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
# In a packaged install the host lives in /usr/lib; in a git checkout it sits
# next to this script.
if [ -x /usr/lib/daryafter/daryafter-native-host ]; then
    host=/usr/lib/daryafter/daryafter-native-host
else
    host="$here/daryafter_native_host.py"
    [ -x "$host" ] || chmod +x "$host"
fi

firefox_dir="$HOME/.mozilla/native-messaging-hosts"
chrome_dir="$HOME/.config/google-chrome/NativeMessagingHosts"
chromium_dir="$HOME/.config/chromium/NativeMessagingHosts"

manifest_name="daryafter.json"

firefox_manifest() {
    cat <<EOF
{
  "name": "daryafter",
  "description": "Starts the Daryafter download manager when the browser extension needs it.",
  "path": "$host",
  "type": "stdio",
  "allowed_extensions": ["daryafter@daryafter.local"]
}
EOF
}

chrome_manifest() {
    id="$1"
    cat <<EOF
{
  "name": "daryafter",
  "description": "Starts the Daryafter download manager when the browser extension needs it.",
  "path": "$host",
  "type": "stdio",
  "allowed_origins": ["chrome-extension://$id/*"]
}
EOF
}

install_firefox() {
    mkdir -p "$firefox_dir"
    firefox_manifest > "$firefox_dir/$manifest_name"
    echo "installed: $firefox_dir/$manifest_name"
}

install_chrome_like() {
    # $1 = directory, $2 = human name
    if [ -n "${CHROME_ID:-}" ]; then
        mkdir -p "$1"
        chrome_manifest "$CHROME_ID" > "$1/$manifest_name"
        echo "installed: $1/$manifest_name ($2, extension ID $CHROME_ID)"
    else
        echo "skipped $2: set CHROME_ID=<extension ID from chrome://extensions> first" >&2
    fi
}

case "${1:-}" in
    --firefox-only)
        install_firefox
        ;;
    "")
        install_firefox
        install_chrome_like "$chrome_dir" "Chrome"
        install_chrome_like "$chromium_dir" "Chromium"
        ;;
    *)
        echo "usage: $0 [--firefox-only]" >&2
        exit 2
        ;;
esac

echo "host script: $host"
