# Frontend progressive delivery

The optional frontend blue/green path keeps Jenkins responsible for immutable
builds and verification, Argo CD for approved Git reconciliation, and Argo
Rollouts for candidate checks and traffic recovery. All environments initially
have `progressiveDelivery.enabled: false`. Backends retain native Deployments.

## Release behavior

1. Jenkins publishes the immutable frontend package and opens a release PR.
2. Protected validation checks native and laptop profiles, strict custom-resource
   schemas, and the exact trusted controller/analysis resources. Production still
   requires human review.
3. Argo CD updates the frontend Deployment pod template. A Rollout references that
   template and creates its own ReplicaSets. Once healthy it scales the reference
   Deployment to zero; that Deployment remains the Git-owned source of images.
4. A ready candidate receives preview traffic only. Pre-promotion analysis checks
   dependency readiness, product data and a synthetic full checkout.
5. Rollouts switches the active Service to the candidate. Post-promotion checks
   repeat functional checkout and readiness/product probes before accepting it.
6. Failed analysis automatically aborts and returns the active Service to the
   retained stable ReplicaSet. The attempted desired version remains in Git and
   the Rollout is Degraded. Jenkins must fail and block promotion, even when old
   stable traffic is healthy. Operators fix forward or use a reviewed Git revert.

Pre checks use three Web samples and one checkout Job. Post checks use twelve
Web samples at ten-second intervals and three checkout Jobs. Jobs have a
90-second deadline and no retries. Recovery is bounded by this observation
window, sample timing, routing propagation and controller availability; it is
not a guarantee of instantaneous or continuous rollback after any later failure.
Readiness failure cannot cut over traffic. The controller can defer its progress
abort timer while an older ReplicaSet has a scale-down deadline. Retaining a
stable version protects traffic during that wait; it does not imply immediate
abort. Old versions are retained for 600 seconds, with one delayed old revision.

Synthetic checkouts create demo orders and exercise dependencies. They must use
synthetic data and compatible APIs/schema. Rollback cannot reverse database
writes or incompatible migrations. The analysis runner is a separately reviewed,
immutable previously scanned frontend image; app releases cannot replace its
probe code or credentials. It has no Kubernetes API token.

## Installation and activation order

1. Review and merge platform verifier support. Apply its read-only Jenkins
   verification RBAC. It adds ReplicaSet reads and named frontend Rollout/Service
   reads, never Secrets or mutation privileges.
2. Review and merge the CI verifier integration. Keep the shared-library pin
   unchanged. Verify the native path still succeeds.
3. Review and merge this GitOps support change with feature flags OFF. This also
   installs the protected custom-resource validation policy for later PRs.
   GitOps configuration requires real code-owner review; automation must not
   self-approve or bypass branch protection.
4. Install the checksum-locked CRDs with the reviewed renderer:
   `python3 platform/argo-rollouts/render-controller.py --crds | kubectl apply --server-side -f -`.
   The CRDs are cluster-wide; each controller's Role/RoleBinding is namespaced.
5. Activate dev using a separate reviewed config PR: set the dev laptop profile's
   `progressiveDelivery.enabled: true`, set `apiServerCIDR` to the actual IPv4
   Kubernetes API endpoint with `/32`, and set the matching dev ApplicationSet
   element's `progressiveDelivery: true`. Apply the reviewed ApplicationSet
   bootstrap so Argo CD respects the two controller-owned fields before sync.
   Do not combine initial migration with an image change. Initial Rollout revision
   1 has no prior stable version and skips analysis; migrate the already verified
   current image and verify public smoke plus browser checkout afterward.
6. Verify exact serving image/hash/replicas with Jenkins, public checks and
   controller metrics. Repeat the reviewed activation for staging. Prepare
   production separately after that evidence; keep its image selection unchanged
   during migration and require human review.

Argo CD ignores only the reference frontend Deployment replica count and the
Rollouts hash selector on the two frontend Services. Image, pod template, policy
and analysis remain reconciled. Namespace controllers need API port 6443 to the
exact configured /32 and frontend/DNS access. Recheck that address after cluster
recreation. Application quotas need capacity for the native source and blue/green
pods during migration and for synthetic Jobs. Controller resources are bounded.

## Verification and response

The protected verifier checks observed generations, successful current-revision
pre/post analysis (except initial revision 1), stable/current/active hash agreement,
active Service selector and ReplicaSet owner UID, immutable expected image and
ready replica count. Manual full promotion is rejected. Recovery to an older
stable version never counts as success for a newer requested release.

### Failed release

On abort, inspect `kubectl -n boutique-ENV get rollout frontend -o yaml`,
`get analysisruns,jobs`, and controller logs. Archive the failed state and active
selector before fixing forward or using the existing reviewed rollback runbook.
Do not repeatedly retry or manually promote a failed candidate to make the
pipeline green. Escalate unavailable controllers, dependency faults, or continued
user impact through the existing incident process.

### Controller unavailable

Inspect the namespace's `argo-rollouts` Deployment, Pod events and controller
logs. Confirm the configured API endpoint, DNS and NetworkPolicy permit the
controller's scoped access. Restore the reviewed controller configuration before
attempting another release. Existing Service selectors continue routing to their
selected pods, but analysis and automatic traffic recovery require the controller.
Do not delete the Rollout or disable the feature during an incident: the native
reference Deployment may have zero replicas, and pruning controller-owned resources
can interrupt serving traffic. Returning to native Deployments needs a separate
reviewed migration that establishes healthy native replicas and switches the
Service before removing the Rollout and its Argo field ignores.

Prometheus discovers app-namespace controllers on port 8090 and alerts for
Degraded frontend releases and unavailable controllers. This change alone does
not establish end-to-end Slack delivery; verify that separately. An aborted
Rollout may remain Degraded while its previous stable version serves correctly.

## Evidence and limits

`tests/progressive_delivery_live.py` targets only `boutique-rollouts-check` and
uses the actual pinned controller and analysis Jobs with an in-memory test app.
It proves promotion, readiness protection, pre-analysis abort, observed candidate
traffic followed by automatic post-switch fallback, and subsequent forward
recovery. Only fixture sampling periods are shortened. This experiment does not
prove public ingress behavior or application migration; those require dev/staging
activation and real public smoke/browser checks. A no-cutover readiness check is
reported separately from a completed automatic abort.

Run `KUBECONFORM=/path/to/kubeconform python3 -m unittest discover -s tests -p
'test_progressive_manifests.py'` and the full protected `scripts/validate.sh` before
publishing configuration changes. Do not use missing-schema skips for Rollouts.
