#!/usr/bin/env bash
set -euo pipefail
TOOLS=$(cd "$(dirname "$0")" && pwd)
ROOT=${1:-"$(dirname "$TOOLS")"}
ROOT=$(cd "$ROOT" && pwd)
BASE_REF=${2:-}
# Helm inputs cannot traverse into agent state; candidate files are data only.
VALIDATION_SCOPE=$(python3 - "$ROOT" "$TOOLS" "$BASE_REF" <<'INPUTS'
from pathlib import Path
import sys
root=Path(sys.argv[1])
sys.path.insert(0, sys.argv[2])
from helm_release import selected_chart
from release_config import ENVIRONMENTS, SERVICES, validation_environments
for folder in ('environments','lab-profiles','laptop-profiles','monitoring','dependencies','platform'):
    for path in (root/folder).rglob('*'):
        if path.is_symlink(): raise SystemExit('Symlinks are not allowed in Helm/configuration inputs')
for environment in ENVIRONMENTS:
    for service in SERVICES:
        selected_chart(root, service, environment)
scoped = validation_environments(root, sys.argv[3])
print(' '.join(scoped) if scoped else 'full')
INPUTS
)
environments=(dev staging production)
if [ "$VALIDATION_SCOPE" != full ]; then
  read -r -a environments <<< "$VALIDATION_SCOPE"
fi
echo "Manifest validation scope: $VALIDATION_SCOPE"
PRIVATE_VALIDATION=$(mktemp -d)
trap 'rm -rf "$PRIVATE_VALIDATION"' EXIT
export KUBECONFIG="$PRIVATE_VALIDATION/unavailable"
# Reuse the same strict/versioned schemas across profiles within this private run.
mkdir -p "$PRIVATE_VALIDATION/schemas"
# CRD schemas come from protected tools and checksum-locked upstream manifests.
python3 "$TOOLS/../platform/argo-rollouts/make-schemas.py" "$PRIVATE_VALIDATION/rollouts"
# Schema and image-policy checks consume exactly the same protected render.
SCHEMA_ARGS=(-cache "$PRIVATE_VALIDATION/schemas"
  -schema-location "$PRIVATE_VALIDATION/rollouts/{{ .ResourceKind }}_{{ .ResourceAPIVersion }}.json"
  -schema-location default -strict -summary -kubernetes-version 1.34.0)
for environment in "${environments[@]}"; do
  for profile in cloud lab laptop; do
    manifest="$PRIVATE_VALIDATION/$environment-$profile.yaml"
    python3 "$TOOLS/render.py" "$environment" --root "$ROOT" --profile "$profile" --lint
    python3 "$TOOLS/render.py" "$environment" --root "$ROOT" --profile "$profile" > "$manifest"
    skip=()
    if [ "$profile" != laptop ]; then skip=(-skip Certificate,Issuer); fi
    kubeconform "${SCHEMA_ARGS[@]}" "${skip[@]}" "$manifest"
    python3 "$TOOLS/check_rendered_images.py" --root "$ROOT" --environment "$environment" --profile "$profile" --rendered-file "$manifest"
  done
done
# Release-only changes cannot alter monitoring or auxiliary charts.
if [ "$VALIDATION_SCOPE" != full ]; then exit 0; fi
for profile in homelab nonprod production; do
  python3 "$TOOLS/render-monitoring.py" "$profile" --root "$ROOT" --lint
  python3 "$TOOLS/render-monitoring.py" "$profile" --root "$ROOT" | kubeconform "${SCHEMA_ARGS[@]}"
done
for profile in nonprod production; do
  python3 "$TOOLS/render-monitoring.py" "$profile" --root "$ROOT" --lab --lint
  python3 "$TOOLS/render-monitoring.py" "$profile" --root "$ROOT" --lab | kubeconform "${SCHEMA_ARGS[@]}" -skip Certificate
done
for chart in dependencies/homelab platform/external-secrets/monitoring; do
  helm lint --strict "$ROOT/$chart"
  helm template boutique-aux "$ROOT/$chart" | kubeconform "${SCHEMA_ARGS[@]}" -skip ExternalSecret,SecretStore
done
