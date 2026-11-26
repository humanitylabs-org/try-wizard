# A stand-in for the Mac guest's network side (try-wizard#192): Debian trixie with systemd-resolved as on the WizardOS
# 0.4.0 disk, and no /etc/systemd/resolved.conf.d/50-wizard-dns.conf (#158), like a disk the bundled guest update never
# reached. Docker inside it plays the guest's Docker, which gives the engine container its DNS.
FROM debian:trixie
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      systemd systemd-sysv systemd-resolved python3 iproute2 docker.io docker-cli ca-certificates \
    && rm -rf /var/lib/apt/lists/*
