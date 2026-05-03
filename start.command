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

export HOST_TIMELINE_DATA="${HOST_TIMELINE_DATA:-/mnt/c/TimelineData}"
export HOST_CODEX_HOME="${HOST_CODEX_HOME:-/mnt/c/Users/amano/.codex}"
export HOST_CODEX_BACKUP_HOME="${HOST_CODEX_BACKUP_HOME:-/mnt/c/Codex/archive/migration-backup-2026-03-27/codex-home}"
export HOST_CODEX_ROOT="${HOST_CODEX_ROOT:-/mnt/c/Codex}"

mkdir -p "$HOST_TIMELINE_DATA"
mkdir -p .docker
if command -v flock >/dev/null 2>&1; then
  flock .docker/docker-compose.lock docker compose up -d --build worker
else
  docker compose up -d --build worker
fi

echo
echo "TimelineForWindowsCodex worker-1 was started."
echo "CLI commands execute inside this persistent Compose service container."
echo
echo "CLI examples:"
echo "  ./cli.command settings status"
echo "  ./cli.command items list --json"
echo "  ./cli.command items refresh --json"
echo "  ./cli.command items download --to C:\\TimelineData\\windows-codex-downloads"
