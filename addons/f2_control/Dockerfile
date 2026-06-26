ARG BUILD_FROM
FROM ${BUILD_FROM}

RUN pip3 install --no-cache-dir requests

# vendored: the pure engine package + the IO-shell controller
COPY f2_control /app
WORKDIR /app

COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
