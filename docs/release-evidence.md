# Verified delivery and recovery

An image selected in Git is not proof of a successful deployment. Staging
promotion requires a recent signed verification of that exact image in dev;
production promotion requires equivalent staging evidence and the Jenkins
production approval. The evidence also identifies the GitOps commit that Argo CD
actually synchronized. This commit must remain in the checked-out main history,
and its source-environment overlay must select the same image.

## Trust boundary

The release controller owns the `boutique-verify` job and an Ed25519 private key.
Only this trusted job can access the `release-evidence-signing-key` file
credential. The promotion and rollback jobs receive the separately installed
`release-evidence-public-key` credential. Never accept a public key supplied
inside an artifact, by a job parameter, or from a source pull request. Protect
the trusted pipeline repository and its main branch; anyone able to change the
trusted verifier or read its private key can manufacture successful evidence.

Provision keys outside Git with:

```sh
umask 077
openssl genpkey -algorithm ED25519 -out verification-private.pem
openssl pkey -in verification-private.pem -pubout -out verification-public.pem
```

Store the private key in Jenkins credentials and remove local copies after
secure provisioning. No real key is included in this repository. Rotation uses
a new public-key credential and requires re-verification for new promotions;
old signatures are intentionally rejected after replacing the trusted key.

Retrieve evidence with Jenkins Copy Artifact from the fixed trusted verification
job and an explicit build number. Do not fetch an arbitrary caller-provided URL,
copy from a PR job, use “last successful build” without matching its digest, or
trust a boolean supplied by the person requesting promotion. Archive the signed
envelope plus the measured reports in that verification build. Retain successful
production verification builds for rollback and audit.

## What the verifier measures

After rollout and functional smoke tests, the trusted verifier captures:

* Kubernetes Deployment generation, observed generation, replica counts,
  availability/progress conditions, and selected immutable image.
* Nonterminating service Pods in the expected namespace: each must be Running
  and Ready, with the requested image in its spec and runtime image ID. The ready
  pod count must match the Deployment's desired count.
* The `boutique-ENV` Argo CD Application in `argocd`: its repository and source
  profile, Synced/Healthy status, and synchronized commit. Accepted source paths
  are `environments/ENV` and `lab-profiles/ENV`.
* Actual smoke-test completion: browse, cart, validation, origin protection,
  session isolation, server pricing, checkout, repeat/concurrent idempotency,
  order ownership, empty cart, and deletion. Reports contain the trusted origin,
  environment, UTC timestamps, and successful completed checks. The issuer
  rejects incomplete or old smoke reports.

This project currently releases single-platform images. With multi-platform
images, Kubernetes runtime image IDs can name a platform manifest while Git
selects the OCI index. The strict runtime comparison will deliberately reject
that difference. Add verified registry manifest-to-index resolution before
introducing multi-platform releases; do not relax the digest comparison.

## Commands

Run commands from a complete GitOps checkout containing the synchronized commit.
The signing command checks real report contents before producing an envelope:

```sh
python3 scripts/release_evidence.py create \
  --environment dev --service cart --image "$IMAGE" \
  --gitops-commit "$GITOPS_COMMIT" \
  --deployment-json deployed-release.json --pods-json deployed-pods.json \
  --argocd-json argocd-application.json --smoke-json smoke-report.json \
  --build-url "$BUILD_URL" --signing-key "$SIGNING_KEY" \
  --output release-evidence.json

python3 scripts/promote.py cart staging "$IMAGE" \
  --evidence release-evidence.json --public-key "$PUBLIC_KEY"
```

All commands emit one JSON result containing the immutable image. Promotion
evidence is valid for 24 hours by default, with a small clock-skew allowance.
Jenkins fixes this policy rather than accepting a user-selected freshness
override. Dev selection additionally relies on a separately signed release
attestation from the protected-main build. The local YAML-editing command alone
cannot prove that an image passed the release scan.

## GitOps pull-request policy

The build job signs `release.json` only after tests, image scanning, and SBOM
generation. Use a separate `release-artifact-signing-key` credential; verification
signing credentials belong only to the deployment verifier. Release attestations
identify the service, immutable image, source commit, build URL, and SHA-256 hashes
of archived scan/SBOM reports. Consumers compare the plain release record and
report hashes with the verified signed payload.

```sh
python3 scripts/release_attestation.py sign --record release.json \
  --signing-key "$RELEASE_SIGNING_KEY" --output release-attestation.json

python3 scripts/promote.py cart staging "$IMAGE" \
  --release-record release-attestation.json \
  --release-public-key "$RELEASE_PUBLIC_KEY" \
  --evidence verification-evidence.json --public-key "$PUBLIC_KEY"
```

Promotion and rollback write `promotionrecords/ENV/SERVICE.json` alongside the
image change. Commit both files. Records contain the signed release attestation
and, when required, the signed preceding-environment or same-environment
verification envelope. The record also captures the previous selected image.
These artifacts contain release provenance, rather than credentials or customer
data.

A required GitOps policy check validates records against the current PR base.
It rejects missing/forged records, invalid quality gates, stale verification,
different images/environments, and a changed preceding-environment or target
selection. It verifies history against the base commit rather than trusting new
commits introduced by the PR. A separate render policy checks that base/profile
edits cannot bypass overlay image selection or add unscanned app containers.

Run these tools from a **protected-main tools checkout**, evaluating a separate
PR checkout as data:

```sh
python3 trusted-tools/scripts/check_delivery_change.py \
  --root gitops-pr --base "$BASE_COMMIT" \
  --release-public-key "$RELEASE_PUBLIC_KEY" --evidence-public-key "$PUBLIC_KEY"
python3 trusted-tools/scripts/check_rendered_images.py --root gitops-pr
```

The policy job definition must come from protected CI configuration. A PR must
not be able to replace the policy script or omit the check from its Jenkinsfile.
Require the policy check on GitHub main with strict up-to-date checks, including
administrator enforcement. Changes to protected pipeline/policy configuration
need platform-owner review. Public validation keys can be used on the validation
controller; private signing keys cannot.

Other configuration changes still need review: this policy proves authorized
application image delivery, rather than the safety of every Kubernetes setting.
Use an environment delivery lock shared by promotion and rollback. Release
orchestration should release its agent before waiting for child jobs; the child
verifier must not reacquire the parent's delivery lock.

## Rollback

Select a successful verification build of the preceding known-good release in
the **same environment**. The signed image must have been deployed at an earlier
ancestor commit. A deployment that failed verification cannot become a rollback
candidate. The rollback command checks the expected current digest to reject a
stale request, and never substitutes dev/staging evidence for production proof:

```sh
python3 scripts/rollback.py cart production "$KNOWN_GOOD_IMAGE" \
  --current-image "$CURRENT_IMAGE" --evidence previous-release-evidence.json \
  --public-key "$PUBLIC_KEY"
```

Rollback accepts retained evidence up to 30 days old by default. Re-run routine
verification for long-lived production releases so recovery evidence does not
expire. The operator selects the appropriate prior successful build; this
command validates that candidate and does not discover the latest known-good
artifact automatically. Review database backward compatibility before approving
a rollback. An image rollback does not undo a database migration.

Jenkins requires production approval and opens a reviewed GitOps pull request.
Do not run `kubectl set image` or `rollout undo` as the release workflow: Argo CD
would reconcile them back to Git. After the PR merges, verify the recovered
release again and retain fresh evidence. Require PR checks to rerun on a changed
base branch so a concurrent promotion cannot silently invalidate rollback
review. None of these scripts grants Jenkins or GitHub administrative bypasses.

## Validation limits

The automated tests use real temporary Git histories and Ed25519 keys, with
synthetic Kubernetes/Argo reports. They prove signature, freshness, image,
environment, history, rollout, smoke, and rollback guards. They do not prove a
live deployment. Live Jenkins execution, cluster rollout, Argo synchronization,
and measured smoke reports are separate acceptance checks.
