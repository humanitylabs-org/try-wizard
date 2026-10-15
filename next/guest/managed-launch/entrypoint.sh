#!/bin/sh
# Keep the container available for root maintenance exec while its normal
# bootstrap/services are fenced. Never run migration under a stopped Docker VM.
set -eu
[ -f /wizard-managed-state/admission.lock ] || { printf '%s\n' 'Managed launch state missing' >&2; exit 75; }
while [ -e /wizard-managed-state/lease.json ]; do sleep 1; done
# Preserve stock command/entrypoint semantics exactly.
exec /opt/hermes/docker/entrypoint-dispatch.sh "$@"
