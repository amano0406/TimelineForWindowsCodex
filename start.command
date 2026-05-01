#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -f "settings.json" ]]; then
  cp settings.example.json settings.json
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker Desktop is not installed or docker is not on PATH."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker Desktop is installed but the Docker engine is not ready."
  echo "Start Docker Desktop and wait until the engine is running, then try again."
  exit 1
fi

mkdir -p .docker
if command -v flock >/dev/null 2>&1; then
  flock .docker/docker-compose.lock docker compose up -d --build --remove-orphans worker
else
  docker compose up -d --build --remove-orphans worker
fi

echo
echo "TimelineForWindowsCodex worker was started."
echo "This product is CLI-only; the worker may exit after the refresh command completes."
echo
echo "CLI examples:"
echo "  ./cli.command settings status"
echo "  ./cli.command items list --json"
echo "  ./cli.command items refresh --json"
echo "  ./cli.command items download --to /shared/downloads"
