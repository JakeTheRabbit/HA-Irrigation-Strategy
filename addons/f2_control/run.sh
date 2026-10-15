#!/usr/bin/with-contenv bashio
# Crop Steering Controller entrypoint. SUPERVISOR_TOKEN is injected because homeassistant_api: true.
# Start nginx (serves the dashboards on the ingress port; it daemonizes and returns),
# then run the engine as the foreground/main process so its SIGTERM safe-valve-off still
# fires when the add-on is stopped. nginx is a static file server — if it ever dies the
# UI is briefly down but the engine is unaffected.
# nginx's port has no login of its own, so a standalone container (compose sets F2_RUNTIME=container)
# runs it only when F2_SERVE_UI=1 asks for it. Anything else keeps it, as the Home Assistant app (behind
# ingress) needs it, so an app that lost config.yaml's `environment:` still has its dashboard.
cd /app
if [ "${F2_RUNTIME:-}" != "container" ] || [ "${F2_SERVE_UI:-0}" = "1" ]; then
  nginx || echo "[Crop Steering Controller] nginx failed to start — web UI unavailable, engine continues"
fi
exec python3 controller.py
