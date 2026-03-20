#!/bin/bash
# health-check-lib.sh — Extracted testable functions from health-check.sh

validate_tag_format() {
    local tag="$1"
    [[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]
}

validate_hmac() {
    local tag="$1" secret="$2" actual_sig="$3"
    local expected
    expected=$(echo -n "$tag" | openssl dgst -sha256 -hmac "$secret" | awk '{print $NF}')
    [[ "$expected" == "$actual_sig" ]]
}

read_secret_from_env() {
    local env_file="$1"
    if [ -f "$env_file" ]; then
        grep "^FLASK_SECRET_KEY=" "$env_file" 2>/dev/null | cut -d= -f2- || true
    fi
}
