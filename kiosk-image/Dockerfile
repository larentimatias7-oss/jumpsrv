FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

# Install native Chromium, XRDP, Xorg XRDP backend, XFCE4 desktop, and supervisor
RUN apt-get update && apt-get install -y --no-install-recommends \
    xrdp \
    xorgxrdp \
    xserver-xorg-core \
    xfce4 \
    xfce4-terminal \
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
    && echo "xfce4-session" > /home/kiosk/.xsession \
    && chown kiosk:kiosk /home/kiosk/.xsession

# Remove problematic debian chromium extensions wrapper
RUN rm -f /etc/chromium.d/extensions

# Link chromium to chromium-browser for compatibility
RUN ln -s /usr/bin/chromium /usr/bin/chromium-browser || true

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
