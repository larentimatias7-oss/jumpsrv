FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

# Install native Chromium, XRDP, Xorg XRDP backend, lightweight Openbox, and supervisor
RUN apt-get update && apt-get install -y --no-install-recommends \
    xrdp \
    xorgxrdp \
    xserver-xorg-core \
    openbox \
    chromium \
    dbus-x11 \
    supervisor \
    curl \
    netcat-openbsd \
    ca-certificates \
    procps \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Base kiosk user
RUN useradd -m -s /bin/bash kiosk \
    && echo "kiosk:kiosk" | chpasswd

# Configure XRDP, security negotiation, and PAM
RUN adduser xrdp ssl-cert \
    && sed -i 's/security_layer=negotiate/security_layer=negotiate/g' /etc/xrdp/xrdp.ini \
    && sed -i 's/crypt_level=low/crypt_level=high/g' /etc/xrdp/xrdp.ini \
    && sed -i '1s/^/auth sufficient pam_permit.so\n/' /etc/pam.d/xrdp-sesman \
    && echo "openbox-session" > /home/kiosk/.xsession \
    && chown kiosk:kiosk /home/kiosk/.xsession

# Remove problematic debian chromium extensions wrapper
RUN rm -f /etc/chromium.d/extensions

# Managed Chromium policies
RUN mkdir -p /etc/chromium/policies/managed/
COPY kiosk_policy.json /etc/chromium/policies/managed/kiosk_policy.json

# Copy scripts and supervisor configuration
COPY startwm.sh /etc/xrdp/startwm.sh
COPY supervisor.conf /etc/supervisor/conf.d/supervisor.conf
COPY healthcheck.sh /usr/local/bin/healthcheck.sh
COPY entrypoint.sh /usr/local/bin/entrypoint.sh

RUN chmod +x /etc/xrdp/startwm.sh /usr/local/bin/healthcheck.sh /usr/local/bin/entrypoint.sh \
    && mkdir -p /var/log/supervisor /var/run/xrdp \
    && chown -R xrdp:xrdp /var/run/xrdp

EXPOSE 3389

HEALTHCHECK --interval=30s --timeout=10s --start-period=45s --retries=3 \
    CMD /usr/local/bin/healthcheck.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
