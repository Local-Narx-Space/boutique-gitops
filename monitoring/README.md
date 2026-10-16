# Default mode: Slack and standard observability

Prometheus, Grafana, Alertmanager, Loki and Alloy remain enabled. ServiceNow is
**optional**, with `incidentBridge.enabled=false` by default. In this mode no
incident worker/queue resources render, Alertmanager has only the Slack receiver,
and its secret projection only requires `slack_webhook`.

To practise ServiceNow explicitly, set `incidentBridge.enabled=true`, select a
tested adapter image digest, supply integration credentials and queue data before
syncing. The profiles/queue details below apply to that opt-in mode. Do not enable
it merely to get the app or standard monitoring running.

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

## Homelab Grafana through Cloudflare

The homelab profile enables an NGINX Ingress at grafana.narx.space, scoped
controller access to Grafana TCP 3000, HTTPS root URL, and secure cookies.
Grafana authentication remains enabled. Other monitoring services stay internal.
Reapply applications/monitoring-homelab.yaml to allow Ingress in its AppProject,
then refresh and sync the monitoring Application. In the Debian-hosted Homelab
Cloudflare tunnel add grafana.narx.space with service HTTP 127.0.0.1:80 and
HTTP Host Header grafana.narx.space. Public TLS terminates at Cloudflare;
cloudflared uses HTTP to local NGINX after the encrypted tunnel.

## Grafana plugin updates

Automatic plugin preinstallation and updates are disabled. Bundled Prometheus
and Loki plugins come from the pinned Grafana image. Upgrade that image through
Git instead of modifying bundled plugin files on the read-only root filesystem.
If an earlier startup update unloaded plugins, syncing this environment change
recreates the Grafana pod and restores the bundled plugins from the image.

## Kind API discovery egress

The homelab profile records the current mega-local API backend as
172.18.0.4:6443. Scoped egress policies allow only Prometheus and Alloy to reach
that endpoint after Service destination translation. Existing TCP 443 Service
access remains available. If recreating or moving the cluster, inspect the
default/kubernetes EndpointSlice and update kubernetesApiEndpoint.cidr and port
before syncing. Other profiles do not render this cluster-specific rule.
