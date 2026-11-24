# The image used by every node and by the client.
# If your solution needs another package, add it here.

FROM debian:12-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc

RUN apt-get update \
    && apt-get install -y --no-install-recommends g++ make libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY Makefile .
COPY src/ src/
RUN make

COPY config/ /config/

ENV PATH="/app/bin:${PATH}"
