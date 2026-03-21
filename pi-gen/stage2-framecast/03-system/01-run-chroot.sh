#!/bin/bash -e
set -u -o pipefail
# System hardening steps that run inside the chroot.
# Runs after 03-system/01-run.sh has installed files into the rootfs.

# Firewall: write RFC1918-only rules and enable ufw (C12)
/usr/local/bin/ufw-setup.sh
systemctl enable ufw
