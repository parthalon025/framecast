#!/bin/bash
# FrameCast firewall setup — called during pi-gen image build (chroot).
# Default deny incoming, allow outgoing. Permit only:
#   - 8080/tcp from private networks (web UI)
#   - 5353/udp (mDNS / avahi discovery)
set -eu -o pipefail

# Reset to defaults
ufw --force reset

# Default policies
ufw default deny incoming
ufw default allow outgoing

# Allow web UI from RFC1918 private networks only
ufw allow from 192.168.0.0/16 to any port 8080 proto tcp comment 'FrameCast web UI'
ufw allow from 10.0.0.0/8 to any port 8080 proto tcp comment 'FrameCast web UI'
ufw allow from 172.16.0.0/12 to any port 8080 proto tcp comment 'FrameCast web UI'

# Allow mDNS (avahi) for .local hostname discovery
ufw allow 5353/udp comment 'mDNS (avahi)'

# Enable firewall (non-interactive)
ufw --force enable

echo "FrameCast firewall configured and enabled."
