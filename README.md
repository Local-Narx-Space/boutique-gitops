# GitOps and environment separation

`services/*/base` defines non-root Deployments, ClusterIP Services, probes, resources and token-free service accounts. Overlays select namespace, replica count, frontend origin/cookie policy and image digest. Production uses two app replicas and disruption budgets. No autoscaler is enabled until a measured baseline exists.

`environments/{dev,staging,production}` contains namespace policy, network allowlists and resource quotas. Images begin at the deliberately non-deployable `bootstrap` tag. Use `boutique-bootstrap` for the initial aggregate release of all four services in each environment, with preceding-environment evidence for staging/production. Subsequent releases can promote individual services. Select real immutable digests with the promotion pipeline before syncing a registry-backed environment. Configure GitHub owner references if different from `subhankar12-spec`.

`homelab/*` replaces registry images with locally loaded images and adds per-namespace persistent PostgreSQL/Redis. These are for learning, not HA production databases. Bootstrap secrets using `boutique-platform/scripts/k8s-secrets.py`; existing secrets are preserved. Do not replace database passwords while retaining old PVCs.

## Argo CD

Install a supported, pinned Argo CD chart/version in `argocd` on each target cluster. Apply the corresponding `applications/*.yaml` after repo access is configured. Nonprod hosts dev/staging Applications; production Application belongs on the production cluster, where `https://kubernetes.default.svc` refers to its own cluster. AppProjects restrict repository and destination namespace. Namespace administration remains a bootstrap privilege; scope Argo controller permissions further before multi-tenant use.

Enable the AWS External Secrets operator, then customize/apply `platform/external-secrets/<env>.yaml` with account/region/role values from Terraform outputs. Each SecretStore reads only that environment's secret. Ensure operator RBAC allows token requests for those service accounts. Never commit application credential values.

Install Traefik in namespace `traefik`, cert-manager and a suitable AWS load balancer controller or manually configured load balancer integration. Configure real DNS, issuer email and reviewed chart versions, then apply `platform/ingress/<env>.yaml`. All cloud overlays use HTTPS and Secure cookies; cloud dev also uses HTTPS. Platform controller installation is an explicit bootstrap step, not an automatic side effect of Terraform.

AWS NetworkPolicy enforcement is enabled through VPC CNI configuration. Default kind networking does not enforce NetworkPolicies; use a policy-capable CNI such as Calico (installed by the production lab) before claiming network isolation in the homelab. Verify enforcement with actual connection tests.

Managed data egress currently allows private 10.0.0.0/8 on only the required data port, with AWS security groups limiting data access to cluster nodes/operator. Replace with endpoint-specific CIDRs or stronger pod-level controls when extending the platform.

## Validate

```bash
./scripts/validate.sh
kubectl kustomize homelab/dev | kubeconform -strict -summary -kubernetes-version 1.32.0
```

Monitoring is in `monitoring/profiles/{homelab,nonprod,production}`: Prometheus discovers each app pod, Grafana provisions dashboards, Alertmanager routes to Slack and a durable ServiceNow adapter, and Alloy ships logs to Loki. Target namespaces and read-only discovery permissions are scoped per cluster profile. Supply `monitoring-integrations` through secret settings and select a tested incident-bridge image digest before syncing. See `boutique-platform/docs/monitoring.md` for local mocks, activation and runbooks. `monitoring/production-reference` contains an undeployed HA Prometheus Operator reference; the handwritten stack is single replica. The optional `applications/monitoring-*.yaml` Applications require manual sync so bootstrap secrets/image decisions are explicit.

Signed release attestations, measured deployment evidence, trusted PR policy and reviewed rollback are documented in [release-evidence.md](docs/release-evidence.md). The laptop/VM profile imports the same image overlays; see [production-lab.md](../boutique-platform/docs/production-lab.md).
