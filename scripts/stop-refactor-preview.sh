#!/bin/sh
set -eu
volume=explorer-refactor-preview-db
owner=$(docker volume inspect --format '{{index .Labels "purpose"}}' "$volume" 2>/dev/null || true)
if [ "$owner" != explorer-refactor-preview ]; then
  printf '%s\n' 'Preview volume is missing or has an unexpected owner; no resources removed.' >&2
  exit 1
fi
docker rm -f explorer-refactor-preview-gateway explorer-refactor-preview-api explorer-refactor-preview-db >/dev/null
docker network rm explorer-refactor-preview-private >/dev/null
docker volume rm "$volume" >/dev/null
printf '%s\n' 'Temporary refactor preview removed.'
