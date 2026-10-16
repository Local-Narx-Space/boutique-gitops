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
| `profiles/homelab/values.yaml` | dev, staging, production + monitoring | single-worker SQLite (opt-in only) |
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

## Shared cluster observability

The homelab profile is the shared-cluster profile: application metrics and CRI
logs cover dev, staging and production. It also collects monitoring component
logs and self-metrics. Environment/cluster/service labels keep these populations
separate. One shared stack is not a cross-cluster HA deployment.

### What is deployed

- Application dashboard, platform/monitoring dashboard and production SLO
  dashboard. Incident panels are hidden when ServiceNow delivery is disabled.
- kube-state-metrics v2.20.0: deployment availability, pod phase/restarts and PVC
  state/capacity. Namespace Roles permit list/watch of selected workload objects
  in the three application namespaces and the monitoring namespaces. No Secret
  access, nodes/proxy privilege, ClusterRole or cluster-admin is granted.
- node_exporter v1.12.1: CPU, memory and filesystem telemetry on Linux nodes.
  It runs beside Alloy in monitoring-logs, where host-mounted collectors are
  admitted; the core monitoring namespace remains Pod Security restricted. It
  uses read-only host mounts, non-root execution and no privileged container or
  host network. On kind, node containers share the Debian kernel: host resource
  totals may repeat across node series. Do not sum them as independent hardware.
- Blackbox exporter v0.29.0 probes public HTTPS /health/ready endpoints for all
  three environments, including DNS/TLS/Cloudflare routing. It requires HTTP 200,
  verifies certificates, refuses HTTP and redirects, and never creates orders.
  Missing staging/production Cloudflare routes correctly produce failed probes.
- Multi-window production SLO burn alerts (99.9% availability; 99% under one
  second), plus workload, missing-target, delivery/drop and monitoring-health
  alerts. Minimum 100 eligible events prevents low-volume SLO noise; absence of
  traffic is not proof of success. Service-down/missing alerts are independent.
- Config checksum annotations restart Prometheus, Grafana, Alertmanager and Alloy
  when their mounted configuration changes. Alloy positions persist in a scoped
  per-node host directory; deleting kind nodes still loses their local state.

All exporter images are digest-pinned. Node/blackbox digests were resolved from
upstream Docker Hub manifests. The kube-state-metrics digest comes from the
Kubernetes image promotion manifest in kubernetes/k8s.io; this runner could not
pull registry.k8s.io, so its actual pod startup must be verified on the cluster.

### Slack separation

Alertmanager routes production to slack-production, dev/staging to slack-nonprod,
and platform alerts to the default Slack receiver. Critical production alerts
have a shorter initial delay and repeat interval. The existing slack_webhook key
is intentionally shared by all receivers, as selected for this deployment.
All notifications use one Slack channel with environment labels in their titles.
Logical receiver separation controls alert timing without requiring more channels.

For a dedicated production channel, create its Slack incoming webhook and securely
add it as slack_webhook_production in the existing monitoring-integrations Secret.
Set productionSlackWebhookKey: slack_webhook_production in the homelab values,
commit/review, and sync. Never commit the URL. Leave the existing key in place
for non-production and platform alerts. Receiver tests send no real messages.

### Retention and remaining boundaries

The shared profile retains Prometheus data for up to 35 days with a 4GB block
size cap. Existing 5Gi PVCs are preserved because the current StorageClass cannot
expand them. The size cap can evict data before 35 days; WAL/head storage also
needs free space. Thirty-day SLO compliance is not established until collection
history and capacity support the full window. Loki retention remains seven days.
Production storage planning should provide room for the required retention or a
remote durable metrics/log backend. No PVC is deleted or resized by this change.

Blackbox runs in this same cluster. It cannot report a complete host/cluster
outage after the whole stack disappears. An independent hosted/remote check or
external dead-man receiver remains required. Kubelet/cAdvisor resource usage
and actual per-PVC free-space metrics are not configured; kube-state-metrics
capacity is requested capacity, not free bytes. Secure kubelet serving-cert/RBAC
configuration is required before adding those scrapes. Exporters do not make
single-replica Prometheus, Loki, Grafana, Alertmanager or local storage HA.

### Apply on the current laptop

```bash
cd ~/devops-boutique/boutique-gitops
git pull --ff-only
kubectl --context kind-mega-local apply -f applications/monitoring-homelab.yaml
```

The AppProject now permits namespace-scoped monitoring RBAC in staging and
production. Refresh and sync boutique-monitoring-homelab in Argo CD. No new
secrets are required with the existing Slack fallback. Check monitoring workloads,
Alloy on all eligible nodes, and Prometheus up vectors before assuming collection
works. kube-state-metrics and node-exporter are additional workloads.

Grafana dashboards:
- /d/boutique-overview
- /d/boutique-platform
- /d/boutique-production-slo

Cloud workspace lint/render/native-tool checks do not establish live collection,
Slack delivery, public route reachability or 30-day SLO compliance.

### Validation recorded for this extension

All six profile/incident variants rendered and passed native Prometheus,
Alertmanager routing and Alloy checks. Strict Kubernetes 1.34 schemas passed for
the rendered resource set. Ten monitoring Helm/permission tests passed, including
namespace admission constraints and exclusion of disabled incident components.
Native rule tests cover production burn alerts, healthy/low-volume/non-production
traffic and all twelve missing-service combinations. The blackbox image accepted
its TLS-enforcing configuration. These are configuration tests; live exporter
startup, telemetry, Slack delivery and public route checks remain deployment
acceptance steps on the laptop.
