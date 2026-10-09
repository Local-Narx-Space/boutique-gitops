# Production learning deployment profiles

These profiles inherit `environments/{dev,staging,production}` and therefore consume exactly the same promoted release digests. They add local persisted data services, CA-verified PostgreSQL/Redis TLS, TLS ingress and registry pull credentials. Production retains two application replicas, PDBs and node topology spread.

Use `boutique-platform/scripts/production-lab.py` and its production-lab guide to bootstrap two isolated clusters. Never point the AWS Argo Applications at these local data profiles.

`monitoring/{nonprod,production}` deliberately delivers alerts to internal mock receivers until real integrations are configured. Production uses a dedicated TLS PostgreSQL queue for two adapter replicas. These mocks are an integration test fixture, not live paging. Replace the fixture through a reviewed GitOps change and secret management before depending on external notifications. Local PostgreSQL/Redis remain single replica; the AWS reference uses managed data services.
