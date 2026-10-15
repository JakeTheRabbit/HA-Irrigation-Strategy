# The Supervisor passes BUILD_FROM from build.yaml for each architecture. The default (build.yaml's
# amd64 base, kept equal by a test) lets a plain `docker build addons/f2_control` or the root
# docker-compose.yml build the same image without the Supervisor.
ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.20
FROM ${BUILD_FROM}

# Stopping the app sends SIGTERM to the controller itself, so it gets the whole `timeout:` in
# config.yaml to close the shot in flight. Without this the base image's init signals it only after
# its own services are down and kills it 3 s later, before a slow Home Assistant has answered.
ENV S6_CMD_RECEIVE_SIGNALS=1

# nginx serves the bundled crop-steering dashboards on the ingress port (8420);
# tzdata lets the container honour the Supervisor-injected TZ so the photoperiod /
# dryback / daily-reset windows run on real local time, not UTC.
RUN apk add --no-cache nginx tzdata && rm -rf /var/cache/apk/* /etc/nginx/http.d/*

# requests and its whole dependency closure, exact versions with hashes (requirements.txt), so
# every box's Rebuild installs the same library code. PIP_CONFIG_FILE=/dev/null skips the base
# image's /etc/pip.conf (a second, extra index) so pip reads only PyPI, where the hashes came from.
COPY requirements.txt /tmp/requirements.txt
RUN PIP_CONFIG_FILE=/dev/null pip3 install --no-cache-dir --require-hashes -r /tmp/requirements.txt && rm /tmp/requirements.txt

# vendored: the pure engine package + the IO-shell controller
COPY f2_control /app
# The controller reports its own version (heartbeat -> the dashboard's sidebar). It reads it from
# this copy of the config.yaml Supervisor built the image from: one source of truth, nothing
# to bump anywhere else.
COPY config.yaml /app/addon.yaml
# The licence travels with the image. LICENSE here is a copy of the repository's root LICENSE (the
# build context is this directory, so the root file is out of reach); a test keeps the two equal.
COPY LICENSE /app/LICENSE
WORKDIR /app

# web UI: nginx config + the static dashboards (www/public is written by the dashboard
# build, frontend/scripts/package.mjs, so the dashboards have a single source of truth)
COPY nginx.conf /etc/nginx/nginx.conf
COPY www/public /www/public

COPY run.sh /run.sh
# strip any CRLF (Windows checkout) so the shebang/interpreter resolves, then make executable
RUN sed -i 's/\r$//' /run.sh && chmod a+x /run.sh

CMD [ "/run.sh" ]
