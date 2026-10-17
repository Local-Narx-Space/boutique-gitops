# Boutique GitOps

Argo CD deploys reviewed GitOps main using Helm. Each of the four service repos
owns a chart. Environment umbrella charts store replica/policy settings and
select immutable image digests with versioned chart packages committed in Git.
This keeps the package rendered by Argo in the reviewed tree; the OCI chart is
also published for distribution.

Jenkins opens PRs. The Jenkins `boutique-gitops-validate` job reports the
**boutique/gitops-validation** check. Require it on main, protect production and
configuration/tool changes with CODEOWNERS, and disallow protection bypass.
With CI release automation activated, validated dev/staging bot release PRs
merge automatically; production and rollback retain human review.

## Environment profiles

| Profile | Purpose |
| --- | --- |
| `environments/ENV` | Cloud settings; requires provisioned managed data, secrets, TLS ingress and platform controllers |
| `laptop-profiles/ENV` | Existing Debian/kind environments with independent PostgreSQL/Redis, private GHCR digests and Cloudflare ingress |

Use `applications/laptop-projects.yaml` and `applications/laptop-appset.yaml`
for the existing kind cluster. One ApplicationSet generates independent dev,
staging and production Applications. Dev auto-syncs; staging/production start
paused until their secrets and real release selections are ready. See
[laptop bootstrap and migration](laptop-profiles/README.md). No root app is
required. Cloud/lab definitions remain separate deployment alternatives.
All laptop environments share one host; real production commonly uses separate
clusters/accounts. NetworkPolicy enforcement depends on the installed CNI.

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

See [the deployment guide](https://github.com/subhankar12-spec/boutique-platform/blob/main/docs/deploy-cicd-kind.md).
Never commit credentials. AWS uses scoped ESO/IRSA; laptop secrets are generated
in Kubernetes by the platform secret helper and preserved on reruns.

Monitoring retains Prometheus, Grafana, Alertmanager, Loki and Alloy. Slack is
the default receiver. ServiceNow and its incident queue are opt-in with
`incidentBridge.enabled=true`, a reviewed image digest and securely provisioned
integration credentials. See [the monitoring chart](monitoring/README.md).

Laptop/local application profiles provide PostgreSQL and Redis as part of each
environment. Their databases are managed by the corresponding Argo CD application.

Validation has one entry point: `./scripts/validate.sh`. It renders each application
environment/profile once and shares that manifest between Kubernetes schema and
image/rollout policy checks. Cloud, laptop, monitoring and auxiliary chart
checks remain enabled in the default full run. Jenkins can supply its protected
base revision as a second argument: `./scripts/validate.sh /path/to/candidate origin/main`.
Clean commits changing only environment release selections/chart packages validate
both profiles for the affected environments. Changes to shared files,
monitoring, templates or scripts, an unavailable/non-ancestor base, or a dirty
checkout fall back to full validation. Temporary manifests and schema caches are private to the
validation run and removed afterward.
