#!/bin/sh
set -eu
volume=explorer-refactor-preview-db
owner=$(docker volume inspect --format '{{index .Labels "purpose"}}' "$volume" 2>/dev/null || true)
if [ "$owner" != explorer-refactor-preview ]; then
  printf '%s\n' 'Preview volume is missing or has an unexpected owner; no resources removed.' >&2
  exit 1
fi
# The combined preview shares this network and database. Never destroy its
# dependencies while it is still present, even if its containers are stopped.
for dependent in explorer-refactor-combined-gateway explorer-refactor-market-candidate explorer-refactor-momentum-candidate explorer-refactor-saved-home; do
  if docker container inspect "$dependent" >/dev/null 2>&1; then
    printf '%s\n' "Combined preview resource $dependent still exists; no resources removed." >&2
    exit 1
  fi
done
docker rm -f explorer-refactor-preview-gateway explorer-refactor-preview-api explorer-refactor-preview-db >/dev/null
docker network rm explorer-refactor-preview-private >/dev/null
docker volume rm "$volume" >/dev/null
printf '%s\n' 'Temporary refactor preview removed.'
