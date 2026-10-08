FROM debian:trixie
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      systemd systemd-sysv systemd-resolved udev dbus kmod \
      linux-image-arm64 initramfs-tools \
      sudo socat e2fsprogs ca-certificates curl wget git openssh-client \
      iproute2 iputils-ping procps less nano file unzip xz-utils zstd jq \
      python3 python3-venv locales tzdata \
 && echo "en_US.UTF-8 UTF-8" > /etc/locale.gen && locale-gen \
 && apt-get clean && rm -rf /var/lib/apt/lists/* /usr/share/doc/* /usr/share/man/* /var/cache/apt/*
