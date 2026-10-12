FROM debian:trixie
ENV DEBIAN_FRONTEND=noninteractive
# Base system only. Docker, Runtipi, the Wizard App Manager and the apps come from os.sh, which
# build-image.sh runs inside a real VM (guest/overlay/opt/wizard/bin/wizard-provision).
RUN apt-get update && apt-get install -y --no-install-recommends \
      systemd systemd-sysv systemd-resolved systemd-timesyncd udev dbus dbus-user-session libpam-systemd kmod \
      linux-image-arm64 initramfs-tools \
      sudo socat bindfs e2fsprogs ca-certificates curl wget git gnupg openssh-client \
      iproute2 iptables iputils-ping procps less nano file unzip xz-utils zstd jq \
      python3 python3-yaml python3-aiohttp locales tzdata \
 && echo "en_US.UTF-8 UTF-8" > /etc/locale.gen && locale-gen \
 && apt-get clean && rm -rf /var/lib/apt/lists/* /usr/share/doc/* /usr/share/man/* /var/cache/apt/*
