#!/usr/bin/env bash
# Hosted container entrypoint — seed /data, then start gateway.
# Requires ELOPHANTO_GATEWAY_TOKEN (provisioner-minted).
set -euo pipefail

CODE_ROOT="${ELOPHANTO_CODE_ROOT:-/app}"
DATA_ROOT="${ELOPHANTO_DATA_ROOT:-/data}"
export ELOPHANTO_CLOUD=1
export ELOPHANTO_PROFILE="${ELOPHANTO_PROFILE:-hosted}"
export ELOPHANTO_CODE_ROOT="$CODE_ROOT"
export ELOPHANTO_DATA_ROOT="$DATA_ROOT"
export ELOPHANTO_CONFIG="${ELOPHANTO_CONFIG:-$DATA_ROOT/config.yaml}"

mkdir -p "$DATA_ROOT" "$DATA_ROOT/data" "$DATA_ROOT/knowledge" "$DATA_ROOT/browser-profile"

if [[ ! -f "$ELOPHANTO_CONFIG" ]]; then
  if [[ -f "$CODE_ROOT/config.hosted.yaml" ]]; then
    echo "[hosted] seeding $ELOPHANTO_CONFIG from config.hosted.yaml"
    cp "$CODE_ROOT/config.hosted.yaml" "$ELOPHANTO_CONFIG"
  else
    echo "[hosted] WARNING: no config.hosted.yaml to seed" >&2
  fi
fi

if [[ ! -f "$CODE_ROOT/permissions.hosted.yaml" ]]; then
  echo "[hosted] FATAL: permissions.hosted.yaml missing from image" >&2
  exit 1
fi

if [[ -z "${ELOPHANTO_GATEWAY_TOKEN:-}" ]]; then
  echo "[hosted] FATAL: ELOPHANTO_GATEWAY_TOKEN required" >&2
  exit 1
fi

cd "$CODE_ROOT"
exec uv run python -m cli.main gateway --no-cli --no-dashboard "$@"
