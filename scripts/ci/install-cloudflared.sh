#!/usr/bin/env bash
set -euo pipefail

# Install the latest cloudflared binary for Linux amd64.

curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
  -o /tmp/cloudflared
chmod +x /tmp/cloudflared
sudo mv /tmp/cloudflared /usr/local/bin/cloudflared

echo "cloudflared installed: $(cloudflared --version)"
