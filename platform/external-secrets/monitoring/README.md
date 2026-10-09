# AWS monitoring secret bindings

Apply only to the AWS production cluster after installing External Secrets v1
CRDs and creating the `monitoring` namespace. Set the account/region/role ARN
from Terraform output `platform.monitoring`. The role trusts only the
`monitoring:external-secrets-monitoring` service account and reads only the two
named monitoring secrets, with KMS decryption restricted to those secrets.
The included egress NetworkPolicy permits only the three database subnet CIDRs
from the current AWS production topology on TCP 5432. Compare them with
`platform.monitoring.database_subnet_cidrs` before applying; change the reviewed
binding if the VPC layout changes. The database security group independently
limits callers to the cluster/operator host. This policy supplements the
production monitoring profile's deliberately unconfigured external DB rule.

`monitoring-incident-queue` supplies the production adapter's
`QUEUE_DATABASE_URL` and `postgresql_ca`. The adapter mounts the CA at
`/run/queue-ca/ca.crt` and verifies PostgreSQL hostname and chain. Initialize its
dedicated database login before deploying the adapter. The RDS administrator
secret is intentionally excluded from this store's IAM policy and Kubernetes.

Populate the metadata-only Secrets Manager integration secret with
`slack_webhook`, `webhook_token`, `servicenow_password`, and `grafana_password`.
Use reviewed secret-manager tooling, never Git or Terraform variables. The
integration ExternalSecret remains unready until all keys exist. Configure the
ServiceNow HTTPS base URL and dedicated integration username separately in the
production adapter profile. Enable real notifications only deliberately.

This directory is intentionally separate from application secret bindings and
from the local production-lab bootstrap, which supplies its own TLS PostgreSQL
secret. For optional managed nonprod queues, copy these manifests to a reviewed
nonprod overlay and replace both secret names and the IRSA role with the
nonprod Terraform outputs; do not point nonprod at production secrets.

See `boutique-infrastructure/docs/monitoring-data.md` for initialization,
rotation and restore procedures. Secret env values do not reload in existing
pods; controlled adapter rollout is required after queue credential rotation.
