#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

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
  flock .docker/docker-compose.lock docker compose stop worker
else
  docker compose stop worker
fi
