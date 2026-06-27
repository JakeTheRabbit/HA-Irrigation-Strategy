#!/usr/bin/with-contenv bashio
# F2 Control entrypoint. SUPERVISOR_TOKEN is injected because homeassistant_api: true.
# Start nginx (serves the dashboards on the ingress port; it daemonizes and returns),
# then run the engine as the foreground/main process so its SIGTERM safe-valve-off still
# fires when the add-on is stopped. nginx is a static file server — if it ever dies the
# UI is briefly down but the engine is unaffected.
nginx || echo "[f2-control] nginx failed to start — web UI unavailable, engine continues"
cd /app
exec python3 controller.py
