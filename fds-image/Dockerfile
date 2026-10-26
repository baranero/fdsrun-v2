# FDS runtime image: official NIST Linux bundle (FDS + Smokeview + Intel MPI runtime).
# Built by .github/workflows/fds-image.yml and published as ghcr.io/baranero/fdsrun-v2/fds:<version>.
# The image contains only open-source FDS, so the package can stay public and compute
# machines pull it without credentials.
ARG FDS_VERSION=6.10.1
ARG SMV_VERSION=6.10.1

FROM ubuntu:24.04 AS install
ARG FDS_VERSION
ARG SMV_VERSION
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /tmp
RUN curl -fsSL -o fds.sh "https://github.com/firemodels/fds/releases/download/FDS-${FDS_VERSION}/FDS-${FDS_VERSION}_SMV-${SMV_VERSION}_lnx.sh" \
 && bash fds.sh y \
 && rm fds.sh

FROM ubuntu:24.04
ARG FDS_VERSION
LABEL org.opencontainers.image.source="https://github.com/baranero/fdsrun-v2" \
      org.opencontainers.image.description="FDS ${FDS_VERSION} with Intel MPI runtime" \
      org.opencontainers.image.licenses="NIST public domain (FDS); see firemodels/fds"
# libgfortran etc. are bundled by NIST; keep the base minimal.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libgomp1 && rm -rf /var/lib/apt/lists/*
COPY --from=install /root/FDS/FDS6 /opt/fds
COPY entrypoint.sh /usr/local/bin/fds-entrypoint
RUN chmod +x /usr/local/bin/fds-entrypoint && sed -i 's#/root/FDS/FDS6#/opt/fds#g' /opt/fds/bin/FDS6VARS.sh /opt/fds/bin/SMV6VARS.sh
ENV FDS_VERSION=${FDS_VERSION} OMP_NUM_THREADS=1 I_MPI_PIN=1
WORKDIR /work
ENTRYPOINT ["/usr/local/bin/fds-entrypoint"]
CMD ["fds"]
