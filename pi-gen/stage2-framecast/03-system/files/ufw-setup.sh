#!/bin/bash
# FrameCast firewall setup — writes ufw config files directly.
# Cannot run ufw/iptables commands inside pi-gen chroot (no netfilter).
# ufw reads these files on first boot when the service starts.
set -eu -o pipefail

echo "Writing ufw rules (config-only, no iptables)..."

# Enable ufw on boot via config
sed -i 's/^ENABLED=no/ENABLED=yes/' /etc/ufw/ufw.conf 2>/dev/null || true

# Default policies
sed -i 's/^DEFAULT_INPUT_POLICY=.*/DEFAULT_INPUT_POLICY="DROP"/' /etc/default/ufw 2>/dev/null || true
sed -i 's/^DEFAULT_OUTPUT_POLICY=.*/DEFAULT_OUTPUT_POLICY="ACCEPT"/' /etc/default/ufw 2>/dev/null || true
sed -i 's/^DEFAULT_FORWARD_POLICY=.*/DEFAULT_FORWARD_POLICY="DROP"/' /etc/default/ufw 2>/dev/null || true

# Write user rules file (ufw reads this on startup)
cat > /etc/ufw/user.rules << 'RULES'
*filter
:ufw-user-input - [0:0]
:ufw-user-output - [0:0]
:ufw-user-forward - [0:0]
:ufw-user-limit - [0:0]
:ufw-user-limit-accept - [0:0]

### FrameCast web UI — private networks only (port 8080)
-A ufw-user-input -p tcp --dport 8080 -s 192.168.0.0/16 -j ACCEPT
-A ufw-user-input -p tcp --dport 8080 -s 10.0.0.0/8 -j ACCEPT
-A ufw-user-input -p tcp --dport 8080 -s 172.16.0.0/12 -j ACCEPT

### mDNS (avahi) for .local hostname discovery
-A ufw-user-input -p udp --dport 5353 -j ACCEPT

### SSH — private networks only (service disabled by default)
-A ufw-user-input -p tcp --dport 22 -s 192.168.0.0/16 -j ACCEPT
-A ufw-user-input -p tcp --dport 22 -s 10.0.0.0/8 -j ACCEPT
-A ufw-user-input -p tcp --dport 22 -s 172.16.0.0/12 -j ACCEPT

### Rate limiting
-A ufw-user-limit -m limit --limit 3/minute -j LOG --log-prefix "[UFW LIMIT BLOCK] "
-A ufw-user-limit -j REJECT
-A ufw-user-limit-accept -j ACCEPT

COMMIT
RULES

# IPv6 rules (same structure)
cat > /etc/ufw/user6.rules << 'RULES6'
*filter
:ufw6-user-input - [0:0]
:ufw6-user-output - [0:0]
:ufw6-user-forward - [0:0]
:ufw6-user-limit - [0:0]
:ufw6-user-limit-accept - [0:0]

-A ufw6-user-input -p udp --dport 5353 -j ACCEPT
-A ufw6-user-limit -m limit --limit 3/minute -j LOG --log-prefix "[UFW LIMIT BLOCK] "
-A ufw6-user-limit -j REJECT
-A ufw6-user-limit-accept -j ACCEPT

COMMIT
RULES6

chmod 640 /etc/ufw/user.rules /etc/ufw/user6.rules
echo "FrameCast firewall rules written (applied on first boot)."
