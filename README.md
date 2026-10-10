# Boutique GitOps

Argo CD deploys reviewed GitOps main using Helm. Each of the four service repos
owns a chart. Environment umbrella charts store replica/policy settings and
select immutable image digests with versioned chart packages committed in Git.
This keeps the package rendered by Argo in the reviewed tree; the OCI chart is
also published for distribution.

Jenkins opens PRs. The Jenkins `boutique-gitops-validate` job reports the
**boutique/gitops-validation** check. Require it and independent review on main, protect
configuration/tool changes with CODEOWNERS, and disallow protection bypass.
There is no custom signature-policy job, automatic PR merge or signing key.

## Environment profiles

| Profile | Purpose |
| --- | --- |
| `environments/ENV` | Cloud settings; requires provisioned managed data, secrets, TLS ingress and platform controllers |
| `laptop-profiles/dev` | Existing Debian/kind dev with local PostgreSQL/Redis and GHCR digests; loopback port 8088 |
| `lab-profiles/ENV` | Optional TLS/policy-enforced two-cluster exercise |
| `homelab/ENV` | Optional manual local-image exercise, not the registry CI/CD path |

Use `applications/dev-laptop.yaml` only for existing-kind dev. It starts with
manual sync, allowing inspection of the initial four-service baseline. The
cloud and lab Applications require their own foundation. Production belongs on
a separate cluster/account. Default kindnet does not enforce NetworkPolicy.

Placeholder `bootstrap` tags are deliberately non-deployable. Publish each
service and merge its initial dev PR before connecting/syncing the app.
Staging/production promotion copies the exact image digest and chart package
from the preceding environment. Confirm actual rollout and smoke results during
review. The scripts verify configuration identity, not live deployment success.

Rollback restores one service's previous image/chart from a full protected-main
GitOps commit through a new PR; it does not reset main or restore a database.

```bash
./scripts/validate.sh
python3 scripts/render.py dev --profile laptop --lint
python3 scripts/render.py dev --profile laptop
```

See [Helm delivery](docs/helm-delivery.md) and
[the deployment guide](https://github.com/subhankar12-spec/boutique-platform/blob/main/docs/deploy-cicd-kind.md).
Never commit credentials. AWS uses scoped ESO/IRSA; laptop secrets are generated
in Kubernetes by the platform secret helper and preserved on reruns.

Monitoring retains Prometheus, Grafana, Alertmanager, Loki and Alloy. Slack is
the default receiver. ServiceNow and its incident queue are opt-in with
`incidentBridge.enabled=true`, a reviewed image digest and securely provisioned
integration credentials. See [the monitoring chart](monitoring/README.md).

The standalone `dependencies/homelab` database chart is retained for compatibility.
Current laptop/local application profiles already provide PostgreSQL/Redis;
do not install that standalone chart alongside them in the same namespace.
