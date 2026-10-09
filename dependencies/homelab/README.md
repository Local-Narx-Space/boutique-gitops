# Optional legacy local database Helm chart

This chart preserves the older standalone PostgreSQL/Redis bootstrap resources.
The preferred application local profile already includes its data services;
do not install both into the same namespace.

```bash
helm template boutique-local-data dependencies/homelab \
  | kubectl --namespace boutique-dev apply -f -
```

These single-replica learning databases reference pre-created Secrets and retain
PVCs. Helm templates keep their existing names. Use the production lab profile
for TLS and separate-cluster delivery practice.
