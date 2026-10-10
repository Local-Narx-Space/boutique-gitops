# Helm and immutable release promotion

Service repos own Dockerfiles and `helm/`. Jenkins tests/scans the image, lints
and schema-checks Helm, packages the chart as `0.1.0-SOURCE_COMMIT`, and publishes
the image/chart to GHCR. Source-commit versions are not overwritten. Jenkins
archives the exact chart package, digest and reports after quality gates pass.

`environments/ENV/releases.yaml` contains each service's repository/digest/tag.
For a published release, digest is populated and tag is empty. `Chart.yaml`
contains source-versioned dependencies; `charts/` contains their exact packages.
Argo renders packages committed in Git, rather than fetching a mutable tag.

Dev promotion retrieves the service's archived package and verifies its name,
version and safe archive layout before selecting the digest. Staging copies dev's
image and chart unchanged; production copies staging unchanged. No rebuild or
new chart is accepted on those promotion paths. Human PR review confirms the
preceding environment was deployed and passed smoke tests; Git selection alone
is not proof that it ran.

Initial installation consists of four ordinary service selections before Argo
sync, not a special signed bootstrap pipeline. `bootstrap` packages remain only
as non-deployable source templates until replaced.

Rollback selects the service's image/chart from an earlier protected-main commit
and opens a new PR. Review database migration compatibility before merging.
The script rejects unmerged history and mutable image selections.

`./scripts/validate.sh` performs strict Helm lint and Kubernetes schema validation
for cloud, TLS lab and laptop profiles, plus monitoring/auxiliary charts. Built-in
schemas are checked; custom-resource kinds are explicitly skipped where their
CRD schemas are not bundled. Live cluster admission and functionality remain
separate checks. The manifest job executes protected validation tools; no candidate shell scripts or Jenkinsfiles are run.
