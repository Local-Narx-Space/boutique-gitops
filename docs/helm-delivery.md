# Helm application delivery

Each application repository owns `helm/`: chart templates, default values and a JSON values schema. Its Jenkins PR build lints and renders the chart, validates Kubernetes schemas, tests the image and runs the security gates. Protected-main builds package the chart as `0.1.0-<full source commit>`, push it to `oci://ghcr.io/subhankar12-spec/charts` and publish the tested image by digest. Existing source-commit versions are never overwritten.

The signed version-2 release attestation binds the image digest, source commit, chart version, actual `.tgz` SHA-256, OCI manifest digest, scan and SBOM hashes. `chart.tgz` is a Jenkins build artifact alongside the signed release record. The incident adapter remains an image release; application chart metadata applies to the four application services.

## Environment layout

```text
boutique-frontend/helm/       # one service-owned chart per app repository
boutique-catalogue/helm/
boutique-cart/helm/
boutique-orders/helm/
boutique-gitops/
  environments/{dev,staging,production}/
    Chart.yaml               # umbrella; four exact dependency versions
    charts/*.tgz             # verified packages committed with the release
    values.yaml              # reviewed environment configuration
    releases.yaml            # image selections changed by delivery jobs
    templates/               # namespace, network and quota policy
  lab-profiles/<env>/values.yaml
  homelab/<env>/values.yaml
```

Packages are small and deliberately vendored into the GitOps release tree. Argo renders the same reviewed bytes even if an OCI tag changes or the registry is unavailable. No registry download or Helm dependency update is required during sync. Each environment keeps one Argo Application; each app keeps its own source repository and pipeline. Changing chart templates requires building that service and promoting its new signed package.

Cloud Argo sources use `environments/<env>` with `values.yaml` and `releases.yaml`; the production lab adds `../../lab-profiles/<env>/values.yaml`. Release names and namespaces are `boutique-<env>`. Inline values, parameters, alternate repositories and custom rendering plugins are rejected by deployment verification. Local development adds `homelab/<env>/values.yaml` and locally loaded image tags instead; it does not produce production release evidence.

## Promotion and rollback

Promotion copies the verified package and image into the target environment in one GitOps PR. The protected PR checker evaluates signed provenance, package bytes, trusted Git history and both cloud/lab renders. Staging and production must promote the exact chart and image that passed recent preceding-environment verification. Approval and per-environment locks remain in place.

Verification binds the synchronized Git commit, selected chart SHA-256, actual running image IDs, healthy rollout and HTTPS functional smoke report in a separate signed version-2 envelope. Rollback restores the previously verified package and image through another reviewed PR. Argo CD uses Helm to render; it owns reconciliation. Git history and Argo rollback are the operational history, so `helm rollback` is not the delivery mechanism.

Initial packages use version `0.1.0-bootstrap` and images use a deliberately unavailable `bootstrap` tag. Build all four services, then use `boutique-bootstrap` for each environment before individual-service delivery. Older version-1 evidence does not establish chart identity and must be regenerated. A partially failed registry publication is investigated rather than overwriting its source-SHA tag; publish a new reviewed source commit if a complete signed build record cannot be recovered.

## Local checks

```bash
python3 scripts/render.py dev --lint
python3 scripts/render.py dev --profile lab
python3 scripts/render.py dev --profile local
./scripts/validate.sh
```

The existing Prometheus/Grafana/Alertmanager/Loki manifests still use Kustomize. They have their own monitoring delivery and secrets. The optional HA monitoring reference already uses Helm values; installing it and validating its live HA behavior remains separate work.
