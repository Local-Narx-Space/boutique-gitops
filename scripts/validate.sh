#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
for env in dev staging production; do
  kubectl kustomize "environments/$env" | kubeconform -strict -summary -kubernetes-version 1.34.0
 done
