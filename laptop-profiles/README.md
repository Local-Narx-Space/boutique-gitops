# Three environments on the existing laptop cluster

These profiles use private, digest-selected GHCR releases and local PostgreSQL
and Redis. They do not use the homelab profiles' `:local` image overrides.

| Environment | Namespace | Argo manifest | Public hostname | App replicas |
| --- | --- | --- | --- | --- |
| dev | boutique-dev | applications/dev-laptop.yaml | boutique.narx.space | 1 |
| staging | boutique-staging | applications/staging-laptop.yaml | staging-boutique.narx.space | 1 |
| production | boutique-production | applications/production-laptop.yaml | shop.narx.space | 2 |

Each namespace has independent secrets, PostgreSQL/Redis instances and PVCs.
They share the cluster and physical host; production here is a release stage,
not an independent failure domain or a highly available production service.
Production PDBs and two app replicas do not make its single database redundant.
The new Applications require manual sync. Do not apply their cloud counterparts
on top of them: those use different values and enable automated sync/pruning.

## Release order

1. Run Jenkins boutique-promote with TARGET=staging and SERVICE set to one of
   frontend, catalogue, cart, orders. Leave IMAGE and RELEASE_BUILD empty. Repeat
   for each service, validate and merge each resulting GitOps PR. The pipeline
   copies the existing dev image digest and chart unchanged.
2. Before first sync, inspect environments/staging/releases.yaml and ensure no
   bootstrap selections remain. Create the staging app secrets using the platform
   k8s-secrets.py helper with argument staging and current context kind-mega-local.
   Create a namespace-scoped ghcr-pull credential with read:packages. Credentials
   must never be committed to Git.
3. Apply applications/staging-laptop.yaml, refresh and manually sync its Argo
   Application. Check health, functional checkout and data isolation.
4. In the existing Debian-hosted Cloudflare tunnel add staging-boutique.narx.space
   with service HTTP 127.0.0.1:80 and the matching HTTP Host Header.
5. After staging acceptance, repeat promotion with TARGET=production. It copies
   from staging, not dev. Repeat secrets preparation using argument production,
   then apply applications/production-laptop.yaml and manually sync.
6. Add shop.narx.space to Cloudflare using the same local HTTP service and its
   matching Host Header. These single-level hostnames fit *.narx.space TLS.

Do not sync either environment while it still selects bootstrap releases.
Application secrets must be generated independently per namespace. The image-pull
credential can have the same read-only registry identity, but its Secret must
exist in each namespace. Syncing profiles recreates no databases in dev.

Validate any profile from the repository root:

```bash
python3 scripts/render.py staging --profile laptop --lint
python3 scripts/render.py production --profile laptop --lint
```

Current homelab monitoring discovers dev only. Adding a release environment does
not automatically add it to Prometheus, Alloy or alert scope; expand those via a
separate reviewed monitoring change before declaring its monitoring verified.
