#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

docker_bin=""
if command -v docker >/dev/null 2>&1; then
  docker_bin="docker"
elif command -v docker.exe >/dev/null 2>&1; then
  docker_bin="docker.exe"
elif [[ -x "/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe" ]]; then
  docker_bin="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
fi

if [[ -z "$docker_bin" ]]; then
  echo "docker not found in this WSL distro."
  echo "From Windows PowerShell, in projects/xai-dynamic-routing:"
  echo "  .\\scripts\\web-up.cmd"
  echo "That starts local uvicorn if Docker Desktop is not installed."
  echo "To use containers: install Docker Desktop, enable WSL integration for Ubuntu, then 'docker version' here should work."
  exit 1
fi

"$docker_bin" compose up --build -d
echo "Published on http://127.0.0.1:8765/"
echo "Test: ./scripts/wsl-web-test.sh"
