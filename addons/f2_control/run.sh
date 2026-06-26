#!/usr/bin/with-contenv bashio
# F2 Control entrypoint. SUPERVISOR_TOKEN is injected because homeassistant_api: true.
cd /app
exec python3 controller.py
