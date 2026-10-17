> Current cluster state: all three environments now have autoSync=true after
> release selection and namespace credentials were prepared. For a fresh cluster,
> set unprepared environments to autoSync=false before applying the ApplicationSet.
> Bootstrap instructions below describe that initial preparation phase.

# Three environments on the existing laptop cluster

These profiles use private, digest-selected GHCR releases and local PostgreSQL
and Redis. They do not use the homelab profiles' `:local` image overrides.

| Environment | Namespace | Generated Application | Public hostname | App replicas |
| --- | --- | --- | --- | --- |
| dev | boutique-dev | `boutique-dev` | dev-boutique.narx.space | 1 |
| staging | boutique-staging | `boutique-staging` | staging-boutique.narx.space | 1 |
| production | boutique-production | `boutique-production` | shop.narx.space | 2 |

Each namespace has independent secrets, PostgreSQL/Redis instances and PVCs.
They share the cluster and physical host; production here is a release stage,
not an independent failure domain or a highly available production service.
Production PDBs and two app replicas do not make its single database redundant.
One ApplicationSet generates all three Applications. Dev auto-syncs; staging
and production initially have autoSync=false during bootstrap. Once enabled,
each automatically syncs, prunes removed managed resources and self-heals drift.
Do not apply their cloud counterparts on top: those select different values.

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
3. Set staging autoSync=true in applications/laptop-appset.yaml after its
   prerequisites pass, commit/push and apply the ApplicationSet. Check health,
   functional checkout and data isolation.
4. In the existing Debian-hosted Cloudflare tunnel add staging-boutique.narx.space
   with service HTTP 127.0.0.1:80 and the matching HTTP Host Header.
5. After staging acceptance, repeat promotion with TARGET=production. It copies
   from staging, not dev. Repeat secrets preparation using argument production,
   then enable production autoSync in the ApplicationSet, commit/push and apply.
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

The shared homelab monitoring profile now includes dev, staging and production
metrics, logs and alert scope. Reapply its AppProject and sync monitoring after
upgrading, then verify live collection. See monitoring/README.md for details.

## Normal operation after bootstrap

Once dev and staging have valid releases, secrets and working access,
activate the CI release automation described in boutique-ci/docs/release-flow.md.
Dev and staging promotion PRs then validate and merge automatically. Dev rollout
and synthetic smoke verification must pass before staging promotion is queued.
Staging is also verified. Production promotion remains a human-reviewed PR; Argo
syncs after merge. Rollbacks remain reviewed changes. Do not disable GitHub
protection to make automation work: configure code-owner review for production
and protected code/configuration, plus required GitOps validation for every PR.

## ApplicationSet bootstrap and migration

The ApplicationSet is the source of the three Application definitions. It uses a
List generator and the existing names, projects, source paths and namespaces.
The old standalone laptop Application files were removed to avoid two competing
sources of truth. Cloud Application files are alternative configurations, not
objects to apply alongside the laptop ApplicationSet.

1. Ensure ApplicationSet CRD and controller are installed and healthy:

   ```bash
   kubectl --context kind-mega-local -n argocd get deployment argocd-applicationset-controller
   kubectl --context kind-mega-local get crd applicationsets.argoproj.io
   kubectl --context kind-mega-local -n argocd get applications boutique-dev -o yaml
   ```

2. Check existing boutique Applications are not controlled by another
   ApplicationSet or reconciled by a parent root Application. If they are, remove
   that competing source through its owning configuration before adoption. Do not
   delete Applications, namespaces or PVCs to migrate. The existing unrelated
   root-app is not needed by this design and should be left untouched.

3. After reviewing the manifest and confirming dev prerequisites, bootstrap:

   ```bash
   kubectl --context kind-mega-local apply -f applications/laptop-projects.yaml
   kubectl --context kind-mega-local apply -f applications/laptop-appset.yaml
   kubectl --context kind-mega-local -n argocd get applicationset boutique-laptop
   kubectl --context kind-mega-local -n argocd get applications
   ```

   The controller adopts existing unmanaged Applications by matching their names
   and sets its ownerReference. Dev keeps the same workload identity. Staging and
   production are generated but do not sync automatically while autoSync=false.
   Do not manually click Sync on an unprepared environment.

4. Change autoSync to true for each prepared environment in the generator list,
   commit/push, then reapply applications/laptop-appset.yaml. Make this change in
   the ApplicationSet, not through a generated Application's UI.

No root app is required. An administrator applies AppProjects and ApplicationSet
as bootstrap configuration; the controller manages generated Applications, and
Argo automatically tracks their Git sources. Updates to the ApplicationSet file
itself require this administrator apply step (or a future platform pipeline).
Pushing that file alone does not update the live ApplicationSet.

applicationsSync=create-update avoids controller-driven deletion when a list
entry is removed. preserveResourcesOnDeletion=true avoids adding workload
cascade-deletion finalizers. These are migration/deletion guardrails, not a
replacement for backups or review. Controller-wide policy may further restrict
what an ApplicationSet can do. No migration has been executed on the laptop by
cloud workspace validation.

Validation of this migration: the manifest passed the upstream ApplicationSet
CRD schema; native Go templates rendered all three generated specs and preserved
the previous source, destination, names and projects. Helm lint passed for all
three laptop profiles. This does not validate the controller version or ownership
of Applications on the actual laptop; inspect controller conditions after apply.

References: [ApplicationSet](https://argo-cd.readthedocs.io/en/stable/operator-manual/applicationset/)
and [cluster bootstrapping](https://argo-cd.readthedocs.io/en/stable/operator-manual/cluster-bootstrapping/).
