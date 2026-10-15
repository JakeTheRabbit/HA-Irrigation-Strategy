#!/usr/bin/with-contenv bashio
# Crop Steering Controller entrypoint. SUPERVISOR_TOKEN is injected because homeassistant_api: true.
# Start nginx (serves the dashboards on the ingress port; it daemonizes and returns),
# then run the engine as the foreground/main process so its SIGTERM safe-valve-off still
# fires when the add-on is stopped. nginx is a static file server — if it ever dies the
# UI is briefly down but the engine is unaffected.
# nginx's port has no login of its own, so it runs only for the Home Assistant app (behind ingress) or
# when F2_SERVE_UI=1 asks for it. runtime_env decides which the process is, so this script and the
# controller can never disagree: the app only with F2_RUNTIME=addon (config.yaml's `environment:`), the
# Supervisor's token and no HA_URL; anything else is a standalone container.
cd /app
if [ "$(python3 -c 'import os, runtime_env; print(runtime_env.runtime(os.environ))')" = "addon" ] || [ "${F2_SERVE_UI:-0}" = "1" ]; then
  nginx || echo "[f2-control] nginx failed to start — web UI unavailable, engine continues"
fi
exec python3 controller.py
