#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
docker compose up --build -d
echo "Published on http://127.0.0.1:8765/"
echo "Test: ./scripts/wsl-web-test.sh"
