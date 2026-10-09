# Monitoring External Secrets Helm chart

Review `templates/production.yaml` with the IAM role, region and Secrets Manager
paths from Terraform outputs. Review `templates/network-policy.yaml` against the
actual private data subnet CIDRs. These contain references, not secret values.
Install the reviewed External Secrets operator/CRDs and create the monitoring
namespace before syncing these resources.

```bash
helm lint --strict platform/external-secrets/monitoring
helm template boutique-monitoring-secrets platform/external-secrets/monitoring \
  | kubectl apply -f -
```

This separate chart keeps secret provisioning explicit and preserves the
existing ServiceAccount, SecretStore, ExternalSecrets and network policy.
