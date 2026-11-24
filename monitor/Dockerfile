# Dockerfile -- course staff file, do not modify.
#
# Image for the staff monitor. Same pinned base as the service image, plus
# python3 and the docker SDK, plus a build toolchain so we can build the
# real fis client binary and use it for every normal-activity event.

FROM debian:12-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc

RUN apt-get update \
    && apt-get install -y --no-install-recommends g++ make libssl-dev python3 python3-docker \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY Makefile .
COPY src/ src/
RUN make bin/fis
COPY config/ /config/

ENV PATH="/app/bin:${PATH}"

WORKDIR /app/monitor
COPY monitor/*.py ./
COPY monitor/sequences/ sequences/
COPY monitor/static/ static/

CMD ["python3", "monitor.py"]
