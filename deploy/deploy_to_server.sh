#!/usr/bin/env bash
# Smart-speaker autod deploy
# Based on fira-autonomous-rc-car/deploy/deploy_to_pi.sh pattern
# Run from repo root: bash deploy/deploy_to_server.sh

set -euo pipefail

PI_HOST="${PI_HOST:-anton@antonpetnitsky.com}"
PI_PORT="${PI_PORT:-22}"
REMOTE_DIR="/home/anton/smart-speaker"
SSH_CMD="ssh -p $PI_PORT -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=no"

echo "==> Target: $PI_HOST port $PI_PORT"

# Sync workspace to server via tar-over-SSH (avoids Windows scp null-byte bug)
echo "==> Syncing vendor/irene-va/webapi_client/ + plugins/ + deploy/ via tar-over-SSH ..."
tar cf - \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.git' \
    vendor/irene-va/webapi_client/index.html \
    vendor/irene-va/webapi_client/index.css \
    vendor/irene-va/plugins/plugin_greetings.py \
    vendor/irene-va/plugins_catalog.json \
    vendor/irene-va/voice_profiles.json \
    deploy/deploy_to_server.sh \
    | $SSH_CMD "$PI_HOST" "mkdir -p $REMOTE_DIR && cd $REMOTE_DIR && tar xf -"

echo "==> Verifying no null bytes ..."
$SSH_CMD "$PI_HOST" "python3 -c '
import os, sys
bad = []
for root, dirs, files in os.walk(\"vendor/irene-va/webapi_client\"):
    dirs[:] = [d for d in dirs if d != \"__pycache__\"]
    for f in files:
        path = os.path.join(root, f)
        data = open(path, \"rb\").read()
        if b\"\\\\x00\" in data:
            bad.append(path)
if bad:
    print(\"NULL_BYTES_FOUND:\", bad)
    sys.exit(1)
print(\"NULL_CHECK_PASS\")
'"

echo ""
echo "==> Deploy OK. Quick-start:"
echo "  ssh -p $PI_PORT $PI_HOST"
echo "  docker ps  # verify setup-irene-core-1"
echo "  # If mounted files not refreshed, restart container:"
echo "  docker restart setup-irene-core-1"
