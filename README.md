# GitOps and environment separation

`services/*/base` defines non-root Deployments, ClusterIP Services, probes, resources and token-free service accounts. Overlays select namespace, replica count, frontend origin/cookie policy and image digest. Production uses two app replicas and disruption budgets. No autoscaler is enabled until a measured baseline exists.

`environments/{dev,staging,production}` contains namespace policy, network allowlists and resource quotas. Images begin at the deliberately non-deployable `bootstrap` tag. Initialize all four service image selections before the first sync. Select real immutable digests with the promotion pipeline before syncing a registry-backed environment. Configure GitHub owner references if different from `subhankar12-spec`.

`homelab/*` replaces registry images with locally loaded images and adds per-namespace persistent PostgreSQL/Redis. These are for learning, not HA production databases. Bootstrap secrets using `boutique-platform/scripts/k8s-secrets.py`; existing secrets are preserved. Do not replace database passwords while retaining old PVCs.

## Argo CD

Install a supported, pinned Argo CD chart/version in `argocd` on each target cluster. Apply the corresponding `applications/*.yaml` after repo access is configured. Nonprod hosts dev/staging Applications; production Application belongs on the production cluster, where `https://kubernetes.default.svc` refers to its own cluster. AppProjects restrict repository and destination namespace. Namespace administration remains a bootstrap privilege; scope Argo controller permissions further before multi-tenant use.

Enable the AWS External Secrets operator, then customize/apply `platform/external-secrets/<env>.yaml` with account/region/role values from Terraform outputs. Each SecretStore reads only that environment's secret. Ensure operator RBAC allows token requests for those service accounts. Never commit application credential values.

Install Traefik in namespace `traefik`, cert-manager and a suitable AWS load balancer controller or manually configured load balancer integration. Configure real DNS, issuer email and reviewed chart versions, then apply `platform/ingress/<env>.yaml`. All cloud overlays use HTTPS and Secure cookies; cloud dev also uses HTTPS. Platform controller installation is an explicit bootstrap step, not an automatic side effect of Terraform.

AWS NetworkPolicy enforcement is enabled through VPC CNI configuration. Default kind networking does not enforce NetworkPolicies; use a policy-capable CNI such as Cilium before claiming network isolation in the homelab. Verify enforcement with actual connection tests.

Managed data egress currently allows private 10.0.0.0/8 on only the required data port, with AWS security groups limiting data access to cluster nodes/operator. Replace with endpoint-specific CIDRs or stronger pod-level controls when extending the platform.

## Validate

```bash
./scripts/validate.sh
kubectl kustomize homelab/dev | kubeconform -strict -summary -kubernetes-version 1.32.0
```

Prometheus resources are in `monitoring/`, with failure/error-rate rules. Install them on each cluster; missing-environment targets must be removed from that cluster's scrape config to avoid false alerts. Alert routing is not configured until you select a destination.
