# Boutique monitoring Helm chart

This dependency-free chart owns Prometheus, Grafana, Alertmanager, Loki, Alloy,
incident delivery, persistence, network policy and namespace-scoped discovery.
It preserves the existing affordable monitoring stack; chart packaging does not
make its single-replica components highly available. The separate HA Operator
reference remains in `production-reference/` and has not been deployed.

## Select a deployment profile

| Profile values | Application discovery | Incident queue |
| --- | --- | --- |
| `profiles/homelab/values.yaml` | dev | single-worker SQLite |
| `profiles/nonprod/values.yaml` | dev and staging | single-worker SQLite |
| `profiles/production/values.yaml` | production | two workers sharing PostgreSQL |

Prometheus/rules and Alloy configuration are chart files selected by profile.
Embedded Prometheus and Alertmanager template expressions remain literal;
the chart does not run them through Helm's `tpl` function. Kubernetes names,
PVCs and namespaces are stable across the migration.

For the production lab, add `../lab-profiles/monitoring/<cluster>/values.yaml`.
It enables internal mock receivers and, for production, a local TLS queue
PostgreSQL. The chart's single image selection applies to both cloud and lab.
The default `base` profile preserves the older generic stack; deployment should
explicitly select one of the three named profiles.

```bash
# From the GitOps repository root:
python3 scripts/render-monitoring.py nonprod --lint
python3 scripts/render-monitoring.py nonprod
python3 scripts/render-monitoring.py production --lab
# Direct Helm rendering of the equivalent production lab:
helm template lab-monitoring-production monitoring --namespace monitoring \
  -f monitoring/profiles/production/values.yaml \
  -f lab-profiles/monitoring/production/values.yaml
```

Argo CD points at `monitoring` and selects these same files. Its Application name
and project/destination scope remain unchanged. Existing Argo Applications can
adopt the new source on their next reviewed configuration update; do not run a
parallel Helm install for resources already managed by Argo.

## Configure and release

Use `incidentBridge.image.repository`, `.digest` and `.tag` in the reviewed
profile values. Set the immutable SHA-256 digest from the trusted adapter
release and clear `tag`; mutable release tags are rejected by the chart schema.
The deliberate `replace-with-tested-digest` placeholder is allowed for rendering
only. The production-lab deploy preflight rejects it.

```yaml
incidentBridge:
  image:
    repository: ghcr.io/subhankar12-spec/boutique-incident-bridge
    digest: sha256:REPLACE_WITH_64_HEX_CHARACTERS
    tag: ''
```

Set ServiceNow URL/user in `incidentBridge.spec.template.spec.containers[0].env`
through reviewed values; keep passwords and webhooks in referenced Secrets.
Production retains the shared-queue Secret/CA mount, two replicas and disruption
budget. Do not scale the SQLite profiles to multiple workers.

Local lab values deliberately route to internal mocks and preserve private image
pull Secret references. Cloud profiles require actual TLS queue credentials and
notification configuration. See `boutique-platform/docs/monitoring.md` for
activation, operational checks and known HA limits.
