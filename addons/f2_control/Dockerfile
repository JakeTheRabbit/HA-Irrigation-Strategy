ARG BUILD_FROM
FROM ${BUILD_FROM}

# nginx serves the bundled crop-steering dashboards on the ingress port (8420);
# tzdata lets the container honour the Supervisor-injected TZ so the photoperiod /
# dryback / daily-reset windows run on real local time, not UTC.
RUN apk add --no-cache nginx tzdata && rm -rf /var/cache/apk/* /etc/nginx/http.d/*

RUN pip3 install --no-cache-dir requests

# vendored: the pure engine package + the IO-shell controller
COPY f2_control /app
WORKDIR /app

# web UI: nginx config + the static dashboards (www/public is assembled from the repo
# www/ by scripts/publish_addon.sh, so the dashboards have a single source of truth)
COPY nginx.conf /etc/nginx/nginx.conf
COPY www/public /www/public

COPY run.sh /run.sh
# strip any CRLF (Windows checkout) so the shebang/interpreter resolves, then make executable
RUN sed -i 's/\r$//' /run.sh && chmod a+x /run.sh

CMD [ "/run.sh" ]
