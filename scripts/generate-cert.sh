#!/bin/bash
# generate-cert.sh — Generate a self-signed TLS certificate for HTTPS
#
# Uses MEDIA_DIR to locate the cert directory. Creates a 10-year RSA cert
# with SANs for the machine hostname, .local, localhost, and 127.0.0.1.
set -euo pipefail

CERT_DIR="${MEDIA_DIR:-/home/pi/framecast-data}/certs"
mkdir -p "$CERT_DIR"

if [ -f "$CERT_DIR/server.crt" ] && [ -f "$CERT_DIR/server.key" ]; then
    echo "Certificates already exist"
    exit 0
fi

HOSTNAME=$(hostname)

openssl req -x509 -newkey rsa:2048 -keyout "$CERT_DIR/server.key" \
    -out "$CERT_DIR/server.crt" -days 3650 -nodes \
    -subj "/CN=$HOSTNAME" \
    -addext "subjectAltName=DNS:$HOSTNAME,DNS:$HOSTNAME.local,DNS:localhost,IP:127.0.0.1"

chmod 600 "$CERT_DIR/server.key"

echo "Self-signed certificate generated for $HOSTNAME"
