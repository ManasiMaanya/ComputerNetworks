#!/usr/bin/env bash
set -euo pipefail
BASE="${1:-http://127.0.0.1:8765}"
echo "GET $BASE/health"
curl -fsS "$BASE/health"
echo
echo "GET $BASE/api/topology"
topo="$(curl -fsS "$BASE/api/topology")"
printf '%s' "$topo" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['node_count']==8, d; assert d['edge_count']==11, d; print('nodes', d['node_count'], 'edges', d['edge_count'])"
echo "ok"
