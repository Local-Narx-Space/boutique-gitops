#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
for env in dev staging production; do
  python3 scripts/render.py "$env" --lint
  python3 scripts/render.py "$env" | kubeconform -strict -summary -kubernetes-version 1.34.0
  python3 scripts/render.py "$env" --profile lab --lint
  python3 scripts/render.py "$env" --profile lab | kubeconform -strict -summary -kubernetes-version 1.34.0 -skip Certificate,Issuer
 done
python3 scripts/check_rendered_images.py
for profile in homelab nonprod production; do
  python3 scripts/render-monitoring.py "$profile" --lint
  python3 scripts/render-monitoring.py "$profile" | kubeconform -strict -summary -kubernetes-version 1.34.0
done

for profile in nonprod production; do
  python3 scripts/render-monitoring.py "$profile" --lab --lint
  python3 scripts/render-monitoring.py "$profile" --lab | kubeconform -strict -summary -kubernetes-version 1.34.0 -skip Certificate
done
for chart in dependencies/homelab platform/external-secrets/monitoring; do
  helm lint --strict "$chart"
  helm template boutique-aux "$chart" | kubeconform -strict -summary -kubernetes-version 1.34.0 -skip ExternalSecret,SecretStore
done
