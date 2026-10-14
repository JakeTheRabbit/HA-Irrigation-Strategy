ARG BUILD_FROM
FROM ${BUILD_FROM}

# nginx serves the bundled crop-steering dashboards on the ingress port (8420);
# tzdata lets the container honour the Supervisor-injected TZ so the photoperiod /
# dryback / daily-reset windows run on real local time, not UTC.
RUN apk add --no-cache nginx tzdata && rm -rf /var/cache/apk/* /etc/nginx/http.d/*

# requests and its whole dependency closure, exact versions with hashes (requirements.txt), so
# every box's Rebuild installs the same library code. PIP_CONFIG_FILE=/dev/null skips the base
# image's /etc/pip.conf (a second, extra index) so pip reads only PyPI, where the hashes came from.
COPY requirements.txt /tmp/requirements.txt
RUN PIP_CONFIG_FILE=/dev/null pip3 install --no-cache-dir --require-hashes -r /tmp/requirements.txt && rm /tmp/requirements.txt

# The Anthropic SDK for the optional AI assistant, with its whole closure, exact and hashed
# (requirements-brain.txt, compiled against requirements.txt so shared packages keep one pin).
# Nothing imports it yet. armv7 skips it by name: some of its compiled dependencies publish no
# 32-bit ARM wheel, so trying would make the image's contents depend on the build. An armv7 box
# runs rules. The Supervisor passes BUILD_ARCH; a plain docker build leaves it unset and installs.
ARG BUILD_ARCH
COPY requirements-brain.txt /tmp/requirements-brain.txt
RUN if [ "$BUILD_ARCH" = "armv7" ]; then echo "anthropic SDK skipped on armv7: the brain runs rules on this device"; else PIP_CONFIG_FILE=/dev/null pip3 install --no-cache-dir --require-hashes -r /tmp/requirements-brain.txt; fi && rm /tmp/requirements-brain.txt

# vendored: the pure engine package + the IO-shell controller
COPY f2_control /app
# The controller reports its own version (heartbeat -> the dashboard's sidebar). It reads it from
# this copy of the config.yaml Supervisor built the image from: one source of truth, nothing
# to bump anywhere else.
COPY config.yaml /app/addon.yaml
WORKDIR /app

# web UI: nginx config + the static dashboards (www/public is written by the dashboard
# build, frontend/scripts/package.mjs, so the dashboards have a single source of truth)
COPY nginx.conf /etc/nginx/nginx.conf
COPY www/public /www/public

COPY run.sh /run.sh
# strip any CRLF (Windows checkout) so the shebang/interpreter resolves, then make executable
RUN sed -i 's/\r$//' /run.sh && chmod a+x /run.sh

CMD [ "/run.sh" ]
