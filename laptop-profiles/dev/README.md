# Laptop access through Cloudflare Tunnel

The laptop profile exposes the frontend at https://dev-boutique.narx.space using
NGINX Ingress. Cloudflare terminates public HTTPS, the existing tunnel carries
traffic to Debian, and cloudflared connects to local NGINX over HTTP.
The frontend uses this HTTPS public origin and secure session cookies.

In the Homelab tunnel's published application routes, add:

- Hostname: dev-boutique.narx.space
- Service: HTTP, 127.0.0.1:80
- HTTP Host Header: dev-boutique.narx.space

The cloudflared service must run on the Debian host, where kind publishes port 80.
This route needs no port-forward. Cloudflare manages its proxied DNS record.
Keep backend services internal and registry packages private. Create ghcr-pull
in boutique-dev separately; only its reference belongs in Git.

After pushing changes, hard-refresh and sync the boutique-dev Argo CD Application.
Verify its health and open the public URL. A local route check is:

```bash
curl -I -H 'Host: dev-boutique.narx.space' http://127.0.0.1
```

To use localhost:8088 again, disable laptopIngress.enabled and restore
PUBLIC_ORIGIN=http://localhost:8088 and COOKIE_SECURE=false in this profile,
then sync. The configured public origin must match the browser's origin.

The laptop Ingress also renders a NetworkPolicy permitting ingress-nginx
controller pods in the ingress-nginx namespace to reach frontend TCP port 8080.
The existing default-deny and backend policies remain in place.
