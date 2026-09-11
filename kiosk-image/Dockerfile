FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

# Install native Chromium, XRDP, XFCE4 desktop, and supervisor directly from official Debian repositories
RUN apt-get update && apt-get install -y --no-install-recommends \
    xrdp \
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

# Create kiosk user
RUN useradd -m -s /bin/bash kiosk \
    && echo "kiosk:kiosk" | chpasswd

# Configure XRDP and session
RUN adduser xrdp ssl-cert \
    && echo "xfce4-session" > /home/kiosk/.xsession \
    && chown kiosk:kiosk /home/kiosk/.xsession

# Link chromium to chromium-browser for compatibility
RUN ln -s /usr/bin/chromium /usr/bin/chromium-browser || true

# Copy scripts and supervisor configuration
COPY startwm.sh /etc/xrdp/startwm.sh
COPY supervisor.conf /etc/supervisor/conf.d/supervisor.conf
COPY healthcheck.sh /usr/local/bin/healthcheck.sh

RUN chmod +x /etc/xrdp/startwm.sh /usr/local/bin/healthcheck.sh \
    && mkdir -p /var/log/supervisor /var/run/xrdp \
    && chown -R xrdp:xrdp /var/run/xrdp

EXPOSE 3389

HEALTHCHECK --interval=30s --timeout=10s --start-period=45s --retries=3 \
    CMD /usr/local/bin/healthcheck.sh

CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/supervisord.conf"]
