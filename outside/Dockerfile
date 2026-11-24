# outside/Dockerfile -- course staff file, do not modify.
# "A computer on the internet that has nothing to do with the service."

FROM debian:12-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY outside.py .

EXPOSE 8080 8081
CMD ["python3", "outside.py"]
