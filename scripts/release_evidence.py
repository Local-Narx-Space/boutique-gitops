#!/usr/bin/env python3
"""Create signed release evidence from measured Kubernetes/Argo/smoke reports."""
import argparse
import json
from helm_release import selected_chart, approved_argo_source

from evidence import ROOT, EvidenceError, check_history, read_json, sign, utcnow, validate_identity, validate_payload, verified_evidence


def make_payload(args):
    validate_identity(args.service, args.environment, args.image)
    deployments = read_json(args.deployment_json)
    matches = [item for item in deployments.get("items", []) if item.get("metadata", {}).get("name") == args.service]
    if len(matches) != 1:
        raise EvidenceError("Exactly one measured service Deployment is required")
    deployment = matches[0]
    metadata, spec, status = deployment["metadata"], deployment["spec"], deployment.get("status", {})
    if metadata.get("namespace") != "boutique-" + args.environment:
        raise EvidenceError("Deployment was measured in the wrong environment")
    containers = [container for container in spec["template"]["spec"]["containers"] if container.get("name") == args.service]
    if len(containers) != 1:
        raise EvidenceError("Expected exactly one measured service container")
    conditions = {condition["type"]: condition["status"] for condition in status.get("conditions", [])}
    ready, image_ids = 0, []
    for pod in read_json(args.pods_json).get("items", []):
        pod_metadata, pod_status = pod.get("metadata", {}), pod.get("status", {})
        if pod_metadata.get("deletionTimestamp"):
            continue
        if pod_metadata.get("namespace") != "boutique-" + args.environment or pod_metadata.get("labels", {}).get("app.kubernetes.io/name") != args.service:
            raise EvidenceError("Runtime pod report contains an unexpected service or environment")
        measured = [container for container in pod.get("spec", {}).get("containers", []) if container.get("name") == args.service]
        measured_status = [container for container in pod_status.get("containerStatuses", []) if container.get("name") == args.service]
        if len(measured) != 1 or measured[0].get("image") != args.image or len(measured_status) != 1:
            raise EvidenceError("Runtime pod does not run the requested image")
        healthy = pod_status.get("phase") == "Running" and measured_status[0].get("ready") is True and any(condition.get("type") == "Ready" and condition.get("status") == "True" for condition in pod_status.get("conditions", []))
        if not healthy:
            raise EvidenceError("Runtime service pod is not ready")
        ready += 1
        image_ids.append(measured_status[0].get("imageID", ""))
    argo = read_json(args.argocd_json)
    argo_status = argo.get("status", {})
    if argo.get("metadata", {}).get("name") != "boutique-" + args.environment or argo.get("metadata", {}).get("namespace") != "argocd" or argo.get("spec", {}).get("destination", {}).get("namespace") != "boutique-" + args.environment:
        raise EvidenceError("Argo CD report targets the wrong environment")
    if argo.get("spec", {}).get("source", {}).get("repoURL") != "https://github.com/subhankar12-spec/boutique-gitops.git":
        raise EvidenceError("Argo CD report does not use the trusted GitOps repository")
    approved_argo_source(argo.get("spec",{}).get("source"),args.environment)
    smoke = read_json(args.smoke_json)
    if smoke.get("schema_version") != 1:
        raise EvidenceError("Unsupported smoke report schema")
    frontends = [item for item in deployments.get("items", []) if item.get("metadata", {}).get("name") == "frontend" and item.get("metadata", {}).get("namespace") == "boutique-" + args.environment]
    if len(frontends) != 1:
        raise EvidenceError("Measured frontend Deployment is required to bind the smoke origin")
    frontend_containers = [container for container in frontends[0].get("spec", {}).get("template", {}).get("spec", {}).get("containers", []) if container.get("name") == "frontend"]
    public_origins = [variable.get("value") for container in frontend_containers for variable in container.get("env", []) if variable.get("name") == "PUBLIC_ORIGIN"]
    if len(frontend_containers) != 1 or len(public_origins) != 1 or public_origins[0] != smoke.get("origin"):
        raise EvidenceError("Smoke origin does not match the deployed frontend PUBLIC_ORIGIN")
    payload = {
        "schema_version": 2, "service": args.service, "environment": args.environment,
        "image": args.image, "gitops_commit": args.gitops_commit,
        "chart": selected_chart(ROOT,args.service,args.environment,args.gitops_commit),
        "verified_at": utcnow().isoformat(), "build_url": args.build_url,
        "deployment": {
            "image": containers[0].get("image"), "generation": metadata.get("generation"),
            "observed_generation": status.get("observedGeneration"), "desired_replicas": spec.get("replicas", 1),
            "updated_replicas": status.get("updatedReplicas", 0), "ready_replicas": status.get("readyReplicas", 0),
            "available_replicas": status.get("availableReplicas", 0), "available": conditions.get("Available") == "True",
            "progressing": conditions.get("Progressing") == "True",
        },
        "runtime": {"ready_pods": ready, "image_ids": sorted(set(image_ids))},
        "argocd": {
            "revision": argo_status.get("sync", {}).get("revision"),
            "sync_status": argo_status.get("sync", {}).get("status"),
            "health_status": argo_status.get("health", {}).get("status"),
        },
        "smoke": smoke,
    }
    validate_payload(payload, args.service, args.environment, args.image)
    check_history(ROOT, payload)
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    create = subcommands.add_parser("create")
    for name in ("environment", "service", "image", "gitops-commit", "deployment-json", "pods-json", "argocd-json", "smoke-json", "build-url", "signing-key", "output"):
        create.add_argument("--" + name, required=True)
    verify = subcommands.add_parser("verify")
    for name in ("environment", "service", "image", "evidence", "public-key"):
        verify.add_argument("--" + name, required=True)
    verify.add_argument("--max-age-hours", type=float, default=24)
    args = parser.parse_args()
    try:
        if args.command == "create":
            payload = make_payload(args)
            sign(payload, args.signing_key, args.output)
        else:
            payload = verified_evidence(args.evidence, args.public_key, args.service, args.environment, args.image, max_age_hours=args.max_age_hours)
        print(json.dumps({"image": payload["image"], "environment": payload["environment"], "service": payload["service"], "gitops_commit": payload["gitops_commit"]}))
    except (EvidenceError, OSError, KeyError, TypeError, ValueError) as error:
        parser.exit(1, "Release evidence rejected: " + str(error) + "\n")


if __name__ == "__main__":
    main()
