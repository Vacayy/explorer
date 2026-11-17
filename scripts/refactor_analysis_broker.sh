#!/bin/sh
# The candidate's own market analysis broker (architect #3 6940868059): the private preview broker's settings, with its
# own RPC volume, state directory and token, sharing nothing with the private preview or the public service.
# No network or port: requests come only through the unix socket in its RPC volume, which only the candidate API mounts
# (read-only, with the token the broker writes there). The sandbox image is pinned by digest.
# Residual risk (kept in the handover): the broker holds the Docker socket, so a compromised broker controls the host
# (Colima VM and the mounted home). Mitigations are only these: no network or port, token, pinned image, API-only input.
#   scripts/refactor_analysis_broker.sh create | remove
set -eu
NAME=explorer-refactor-single-analysis-broker
RPC=explorer-analysis-rpc-candidate
STATE=${REFACTOR_SERVER_DATA:-$HOME/server-data}/review/refactor-single/analysis/broker-state  # private parent (700)
IMAGE=explorer-analysis-broker:budget-20261115
SANDBOX=sha256:ceb02ae6462a904a93e9c21de56859a00a4895597393f2fb8d7659192b7af77d  # the private preview's pinned sandbox
case "$1" in
  create)
    if [ ! -d "$STATE" ]; then  # new state, RPC volume and token, once (the official new-only provisioning)
      mkdir -p "$(dirname "$STATE")" && chmod 700 "$(dirname "$STATE")"
      python3 "$HOME/developer/agent-whiteboard/runtime/analysis/provision.py" --state-root "$STATE" --rpc-volume "$RPC" --image-id "$SANDBOX"
    fi
    docker run -d --name "$NAME" --restart unless-stopped --user 10001:10001 --group-add "$(docker run --rm -v /var/run/docker.sock:/s --entrypoint stat "$IMAGE" -c %g /s)" \
      --network none --read-only --tmpfs /tmp:rw,nosuid,nodev,size=256m,mode=1777 --cap-drop ALL \
      --security-opt no-new-privileges:true --memory 512m --label explorer.purpose=refactor-single-analysis-broker \
      -v "$RPC:/run/explorer-analysis" -v "$STATE:/state" -v /var/run/docker.sock:/var/run/docker.sock \
      --entrypoint python "$IMAGE" /opt/analysis/serve.py --rpc /run/explorer-analysis --state /state/broker --image-id "$SANDBOX"
    ;;
  remove)
    docker rm -f "$NAME"
    ;;
esac
