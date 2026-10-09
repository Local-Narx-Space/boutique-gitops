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
  kubectl kustomize "monitoring/profiles/$profile" | kubeconform -strict -summary -kubernetes-version 1.34.0
done
