# A stand-in for the Azure VM: same Ubuntu release, with systemd so services really start.
FROM ubuntu:24.04
RUN apt-get update \
 && apt-get install -y --no-install-recommends systemd systemd-sysv python3 sudo iptables ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --shell /bin/bash preflight
CMD ["/lib/systemd/systemd"]
