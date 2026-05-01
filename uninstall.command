#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

COMPOSE_PROJECT="timeline-for-windows-codex"
APPDATA_VOLUME="${COMPOSE_PROJECT}_app-data"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker Desktop is not installed or docker is not on PATH."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker Desktop is installed but the Docker engine is not ready."
  echo "Start Docker Desktop and wait until the engine is running, then try again."
  exit 1
fi

echo
echo "TimelineForWindowsCodex uninstall"
echo
echo "This will remove:"
echo "  - Docker containers for this project"
echo "  - Docker images built for this project"
echo "  - Docker network for this project"
echo
echo "It will not delete Codex source history, outputs, or downloads."
echo "Optional:"
echo "  - delete saved app data volume"
if [[ -f "settings.json" ]]; then
  echo "  - delete local settings.json"
fi
echo

confirm_yes() {
  local prompt_text="$1"
  local response
  read -r -p "${prompt_text}" response
  case "${response}" in
    y|Y|yes|YES|Yes)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

if ! confirm_yes "Continue with uninstall? (y/n): "; then
  echo "Uninstall canceled."
  exit 1
fi

echo
echo "Stopping and removing Docker resources..."
docker compose down --rmi local --remove-orphans </dev/null

remove_volume_if_exists() {
  local volume_name="$1"
  if docker volume ls --format '{{.Name}}' | grep -Fxq "${volume_name}"; then
    docker volume rm "${volume_name}" >/dev/null
    echo "Removed Docker volume: ${volume_name}"
  fi
}

echo
echo "Saved app data volume:"
echo "  ${APPDATA_VOLUME}"
echo "This contains container-side application state only."
if confirm_yes "Delete saved app data too? (y/n): "; then
  remove_volume_if_exists "${APPDATA_VOLUME}"
  echo "Deleted saved app data volume if it existed."
else
  echo "Kept saved app data volume."
fi

if [[ -f "settings.json" ]]; then
  echo
  echo "Local settings file:"
  echo "  $(pwd)/settings.json"
  echo "This includes source roots and the master output root."
  if confirm_yes "Delete settings.json too? (y/n): "; then
    rm -f "settings.json"
    echo "Deleted settings.json"
  else
    echo "Kept settings.json"
  fi
fi

echo
echo "Uninstall completed."
