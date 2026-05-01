#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -f "settings.json" ]]; then
  cp settings.example.json settings.json
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker Desktop is not installed or docker is not on PATH." >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker Desktop is installed but the Docker engine is not ready." >&2
  echo "Start Docker Desktop and wait until the engine is running, then try again." >&2
  exit 1
fi

mkdir -p .docker
if command -v flock >/dev/null 2>&1; then
  flock .docker/docker-compose.lock docker compose run --rm worker "$@"
else
  docker compose run --rm worker "$@"
fi
