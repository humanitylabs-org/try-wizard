# The local Mac window is the owner: only vsock and guest loopback reach local-proxy.conf. Drop whatever identity
# the caller sent and name the owner the way Tailscale Serve does (owner.conf, written by wizard-local-routes).
proxy_set_header Host $http_host;
proxy_set_header Forwarded "";
proxy_set_header X-Forwarded-For "";
proxy_set_header X-Forwarded-Host "";
proxy_set_header X-Forwarded-Proto "";
proxy_set_header CF-Access-Jwt-Assertion "";
proxy_set_header CF-Connecting-IP "";
proxy_set_header Tailscale-User-Name "";
proxy_set_header Tailscale-User-Profile-Pic "";
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection $connection_upgrade;
include /run/wizard-local-proxy/owner.conf;
