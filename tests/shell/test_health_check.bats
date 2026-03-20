#!/usr/bin/env bats

setup() {
    source "$BATS_TEST_DIRNAME/../../scripts/lib/health-check-lib.sh"
    TEST_DIR=$(mktemp -d)
}

teardown() {
    rm -rf "$TEST_DIR"
}

# --- validate_tag_format ---

@test "validate_tag_format accepts v1.2.3" {
    run validate_tag_format "v1.2.3"
    [ "$status" -eq 0 ]
}

@test "validate_tag_format accepts v0.0.0" {
    run validate_tag_format "v0.0.0"
    [ "$status" -eq 0 ]
}

@test "validate_tag_format accepts v10.20.30" {
    run validate_tag_format "v10.20.30"
    [ "$status" -eq 0 ]
}

@test "validate_tag_format rejects missing v prefix" {
    run validate_tag_format "1.2.3"
    [ "$status" -ne 0 ]
}

@test "validate_tag_format rejects non-numeric" {
    run validate_tag_format "vX.Y.Z"
    [ "$status" -ne 0 ]
}

@test "validate_tag_format rejects empty string" {
    run validate_tag_format ""
    [ "$status" -ne 0 ]
}

@test "validate_tag_format rejects injection attempt" {
    run validate_tag_format "v1.0.0; rm -rf /"
    [ "$status" -ne 0 ]
}

@test "validate_tag_format rejects pre-release suffix" {
    run validate_tag_format "v1.0.0-rc1"
    [ "$status" -ne 0 ]
}

# --- validate_hmac ---

@test "validate_hmac succeeds with correct signature" {
    local tag="v1.2.3"
    local secret="test-secret"
    local sig
    sig=$(echo -n "$tag" | openssl dgst -sha256 -hmac "$secret" | awk '{print $NF}')
    run validate_hmac "$tag" "$secret" "$sig"
    [ "$status" -eq 0 ]
}

@test "validate_hmac fails with wrong signature" {
    run validate_hmac "v1.2.3" "test-secret" "deadbeef"
    [ "$status" -ne 0 ]
}

# --- read_secret_from_env ---

@test "read_secret_from_env reads FLASK_SECRET_KEY from file" {
    echo "FLASK_SECRET_KEY=my-secret-key" > "$TEST_DIR/.env"
    run read_secret_from_env "$TEST_DIR/.env"
    [ "$status" -eq 0 ]
    [ "$output" = "my-secret-key" ]
}

@test "read_secret_from_env returns empty for missing file" {
    run read_secret_from_env "$TEST_DIR/nonexistent"
    [ "$status" -eq 0 ]
    [ -z "$output" ]
}

@test "read_secret_from_env returns empty for file without key" {
    echo "OTHER_VAR=value" > "$TEST_DIR/.env"
    run read_secret_from_env "$TEST_DIR/.env"
    [ "$status" -eq 0 ]
    [ -z "$output" ]
}
