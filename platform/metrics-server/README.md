# Local metrics API for HPA

Pinned upstream Metrics Server v0.9.0, image digest and original manifest checksum
are recorded in release-lock.json. The Helm template preserves upstream RBAC and
adds resource limits and a local-kind-only kubelet TLS option. Default values keep
kubelet certificate verification enabled; values-laptop.yaml skips verification
because kind kubelets use self-signed serving certificates. Do not use that
exception for a customer production cluster.

Bootstrap the scoped Argo project/application with
`kubectl apply -f applications/metrics-server.yaml`. Argo then manages the metrics
components from main. This is the resource metrics API used by HPA and kubectl top;
Prometheus remains the application monitoring system.
