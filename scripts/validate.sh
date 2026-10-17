#!/usr/bin/env bash
set -euo pipefail
TOOLS=$(cd "$(dirname "$0")" && pwd)
ROOT=${1:-"$(dirname "$TOOLS")"}
ROOT=$(cd "$ROOT" && pwd)
# Helm inputs cannot traverse into agent state; candidate files are data only.
python3 - "$ROOT" "$TOOLS" <<'INPUTS'
from pathlib import Path
import sys
root=Path(sys.argv[1])
sys.path.insert(0, sys.argv[2])
from helm_release import selected_chart
from release_config import ENVIRONMENTS, SERVICES
for folder in ('environments','lab-profiles','laptop-profiles','monitoring','dependencies','platform'):
    for path in (root/folder).rglob('*'):
        if path.is_symlink(): raise SystemExit('Symlinks are not allowed in Helm/configuration inputs')
for environment in ENVIRONMENTS:
    for service in SERVICES:
        selected_chart(root, service, environment)
INPUTS
PRIVATE_VALIDATION=$(mktemp -d)
trap 'rm -rf "$PRIVATE_VALIDATION"' EXIT
export KUBECONFIG="$PRIVATE_VALIDATION/unavailable"
# Reuse the same strict/versioned schemas across profiles within this private run.
mkdir -p "$PRIVATE_VALIDATION/schemas"
# CRD schemas come from protected tools and checksum-locked upstream manifests.
python3 "$TOOLS/../platform/argo-rollouts/make-schemas.py" "$PRIVATE_VALIDATION/rollouts"
for environment in dev staging production; do
  for profile in cloud lab; do
    python3 "$TOOLS/render.py" "$environment" --root "$ROOT" --profile "$profile" --lint
    python3 "$TOOLS/render.py" "$environment" --root "$ROOT" --profile "$profile" | kubeconform -cache "$PRIVATE_VALIDATION/schemas" -schema-location "$PRIVATE_VALIDATION/rollouts/{{ .ResourceKind }}_{{ .ResourceAPIVersion }}.json" -schema-location default -strict -summary -kubernetes-version 1.34.0 -skip Certificate,Issuer
  done
done
python3 "$TOOLS/check_rendered_images.py" --root "$ROOT"
for profile in homelab nonprod production; do
  python3 "$TOOLS/render-monitoring.py" "$profile" --root "$ROOT" --lint
  python3 "$TOOLS/render-monitoring.py" "$profile" --root "$ROOT" | kubeconform -cache "$PRIVATE_VALIDATION/schemas" -schema-location "$PRIVATE_VALIDATION/rollouts/{{ .ResourceKind }}_{{ .ResourceAPIVersion }}.json" -schema-location default -strict -summary -kubernetes-version 1.34.0
done
for profile in nonprod production; do
  python3 "$TOOLS/render-monitoring.py" "$profile" --root "$ROOT" --lab --lint
  python3 "$TOOLS/render-monitoring.py" "$profile" --root "$ROOT" --lab | kubeconform -cache "$PRIVATE_VALIDATION/schemas" -schema-location "$PRIVATE_VALIDATION/rollouts/{{ .ResourceKind }}_{{ .ResourceAPIVersion }}.json" -schema-location default -strict -summary -kubernetes-version 1.34.0 -skip Certificate
done
for chart in dependencies/homelab platform/external-secrets/monitoring; do
  helm lint --strict "$ROOT/$chart"
  helm template boutique-aux "$ROOT/$chart" | kubeconform -cache "$PRIVATE_VALIDATION/schemas" -schema-location "$PRIVATE_VALIDATION/rollouts/{{ .ResourceKind }}_{{ .ResourceAPIVersion }}.json" -schema-location default -strict -summary -kubernetes-version 1.34.0 -skip ExternalSecret,SecretStore
done
for environment in dev staging production; do
  python3 "$TOOLS/render.py" "$environment" --root "$ROOT" --profile laptop --lint
  python3 "$TOOLS/render.py" "$environment" --root "$ROOT" --profile laptop | kubeconform -cache "$PRIVATE_VALIDATION/schemas" -schema-location "$PRIVATE_VALIDATION/rollouts/{{ .ResourceKind }}_{{ .ResourceAPIVersion }}.json" -schema-location default -strict -summary -kubernetes-version 1.34.0
done
