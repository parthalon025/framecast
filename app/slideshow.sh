#!/bin/bash
# slideshow.sh - VLC-based photo and video slideshow for Raspberry Pi
# Reads config from .env, watches for new media, auto-restarts VLC
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"

# Parse .env file
load_env() {
    local key value
    if [ ! -f "$ENV_FILE" ]; then
        echo "$(date): WARNING: .env not found at $ENV_FILE, using defaults"
        return
    fi
    while IFS='=' read -r key value; do
        key=$(echo "$key" | tr -d '[:space:]')
        # Strip surrounding quotes and whitespace from value
        value=$(echo "$value" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | sed "s/^['\"]//;s/['\"]$//")
        [[ -z "$key" || "$key" == \#* ]] && continue
        export "$key=$value"
    done < "$ENV_FILE"
}

load_env

MEDIA_DIR="${MEDIA_DIR:-/home/pi/media}"
PHOTO_DURATION="${PHOTO_DURATION:-10}"
SHUFFLE="${SHUFFLE:-yes}"
LOOP="${LOOP:-yes}"
AUTO_REFRESH="${AUTO_REFRESH:-yes}"
REFRESH_INTERVAL="${REFRESH_INTERVAL:-30}"
IMAGE_EXTENSIONS="${IMAGE_EXTENSIONS:-.jpg,.jpeg,.png,.bmp,.gif,.webp,.tiff}"
VIDEO_EXTENSIONS="${VIDEO_EXTENSIONS:-.mp4,.mkv,.avi,.mov,.webm,.m4v,.mpg,.mpeg}"

# Validate numeric values
if ! [[ "$PHOTO_DURATION" =~ ^[0-9]+$ ]] || [ "$PHOTO_DURATION" -lt 1 ]; then
    echo "$(date): WARNING: Invalid PHOTO_DURATION, using 10"
    PHOTO_DURATION=10
fi
if ! [[ "$REFRESH_INTERVAL" =~ ^[0-9]+$ ]] || [ "$REFRESH_INTERVAL" -lt 5 ]; then
    echo "$(date): WARNING: Invalid REFRESH_INTERVAL, using 30"
    REFRESH_INTERVAL=30
fi

# Use a user-specific runtime dir for the playlist
RUNTIME_DIR="/tmp/pi-photo-display-$(id -u)"
mkdir -p "$RUNTIME_DIR"
PLAYLIST_FILE="${RUNTIME_DIR}/playlist.m3u"

VLC_PID=""
LAST_HASH=""
SLEEP_PID=""
CONSECUTIVE_FAILURES=0
MAX_FAILURES=5
BACKOFF_SECONDS=60
VLC_START_TIME=0
VLC_RESTART_INTERVAL=21600  # 6 hours in seconds - proactive restart to prevent memory leaks
LAST_SELFTEST_TIME=0
SELFTEST_INTERVAL=3600  # 1 hour
QUARANTINE_DIR="${MEDIA_DIR}/quarantine"
MIN_AVAILABLE_MB=100  # Restart VLC if available memory drops below this

# Check available memory from /proc/meminfo (returns available MB)
get_available_memory_mb() {
    local mem_available
    mem_available=$(awk '/^MemAvailable:/ {print int($2 / 1024)}' /proc/meminfo 2>/dev/null || echo "0")
    echo "$mem_available"
}

# Quarantine the most recently added file to self-heal from corrupt media
quarantine_latest_file() {
    local latest
    latest=$(find_media | xargs -r stat --format='%Y %n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)
    if [ -n "$latest" ] && [ -f "$latest" ]; then
        mkdir -p "$QUARANTINE_DIR"
        local basename
        basename=$(basename "$latest")
        mv "$latest" "${QUARANTINE_DIR}/${basename}"
        echo "$(date): QUARANTINE: Moved suspect file '${basename}' to ${QUARANTINE_DIR}/"
        echo "$(date): QUARANTINE: File was likely corrupt and causing VLC crashes"
        CONSECUTIVE_FAILURES=0
    else
        echo "$(date): QUARANTINE: No media file found to quarantine"
    fi
}

# Periodic self-test: verify system health every hour
run_selftest() {
    local now failures
    now=$(date +%s)
    if [ $((now - LAST_SELFTEST_TIME)) -lt "$SELFTEST_INTERVAL" ]; then
        return
    fi
    LAST_SELFTEST_TIME=$now
    failures=0

    echo "$(date): SELFTEST: Running periodic health check..."

    # Check 1: VLC is responding (if it should be running)
    if [ -n "$VLC_PID" ] && kill -0 "$VLC_PID" 2>/dev/null; then
        echo "$(date): SELFTEST: [OK] VLC running (PID $VLC_PID)"
    elif [ -n "$VLC_PID" ]; then
        echo "$(date): SELFTEST: [FAIL] VLC PID $VLC_PID is not responding"
        failures=$((failures + 1))
    else
        echo "$(date): SELFTEST: [INFO] VLC not running (no media or starting)"
    fi

    # Check 2: Disk space
    local disk_pct
    disk_pct=$(df "$MEDIA_DIR" 2>/dev/null | awk 'NR==2 {gsub(/%/,""); print $5}' || echo "0")
    if [ "$disk_pct" -ge 95 ] 2>/dev/null; then
        echo "$(date): SELFTEST: [WARN] Disk usage at ${disk_pct}% - critically high"
        failures=$((failures + 1))
    else
        echo "$(date): SELFTEST: [OK] Disk usage at ${disk_pct}%"
    fi

    # Check 3: .env is readable
    if [ -f "$ENV_FILE" ] && [ -r "$ENV_FILE" ] && [ -s "$ENV_FILE" ]; then
        echo "$(date): SELFTEST: [OK] .env file readable"
    else
        echo "$(date): SELFTEST: [WARN] .env file missing, empty, or unreadable"
        failures=$((failures + 1))
    fi

    # Check 4: Media directory exists and is writable
    if [ -d "$MEDIA_DIR" ] && [ -w "$MEDIA_DIR" ]; then
        echo "$(date): SELFTEST: [OK] Media directory accessible"
    else
        echo "$(date): SELFTEST: [FAIL] Media directory missing or not writable"
        failures=$((failures + 1))
    fi

    # Check 5: Available memory
    local mem_avail
    mem_avail=$(get_available_memory_mb)
    echo "$(date): SELFTEST: [INFO] Available memory: ${mem_avail}MB"

    if [ "$failures" -eq 0 ]; then
        echo "$(date): SELFTEST: All checks passed"
    else
        echo "$(date): SELFTEST: ${failures} check(s) failed - review warnings above"
    fi
}

# Self-heal .env: if missing/empty/corrupt, restore from .env.example
heal_env_file() {
    local env_example="${SCRIPT_DIR}/.env.example"
    if [ -f "$ENV_FILE" ] && [ -s "$ENV_FILE" ]; then
        return 0
    fi
    echo "$(date): CRITICAL: .env file is missing or empty at $ENV_FILE"
    if [ -f "$env_example" ]; then
        echo "$(date): Self-healing: Restoring .env from .env.example"
        cp "$env_example" "$ENV_FILE"
        # Regenerate secret key
        if command -v python3 &>/dev/null; then
            local new_secret
            new_secret=$(python3 -c "import secrets; print(secrets.token_hex(24))" 2>/dev/null || echo "")
            if [ -n "$new_secret" ]; then
                sed -i "s|^FLASK_SECRET_KEY=.*|FLASK_SECRET_KEY=${new_secret}|" "$ENV_FILE"
                echo "$(date): Self-healing: Generated new FLASK_SECRET_KEY"
            fi
        fi
        echo "$(date): Self-healing: .env restored - review settings in web UI"
        # Reload config from restored file
        load_env
    else
        echo "$(date): CRITICAL: No .env.example found at $env_example - cannot self-heal"
        echo "$(date): CRITICAL: Using built-in defaults only"
    fi
}

# Build find args array from comma-separated extensions
FIND_ARGS=()
first=true
ALL_EXTENSIONS="${IMAGE_EXTENSIONS},${VIDEO_EXTENSIONS}"
IFS=',' read -ra EXT_ARR <<< "$ALL_EXTENSIONS"
for ext in "${EXT_ARR[@]}"; do
    ext=$(echo "$ext" | tr -d '[:space:]' | sed 's/^\.//')
    [ -z "$ext" ] && continue
    if [ "$first" = true ]; then
        FIND_ARGS+=(-iname "*.${ext}")
        first=false
    else
        FIND_ARGS+=(-o -iname "*.${ext}")
    fi
done

# Single function to find all media files (DRY)
# Excludes quarantine directory, thumbnails, and temp files
find_media() {
    find "$MEDIA_DIR" -path "${QUARANTINE_DIR}" -prune -o -path "${MEDIA_DIR}/thumbnails" -prune -o -type f \( "${FIND_ARGS[@]}" \) -not -name "*.tmp" -print 2>/dev/null
}

# Build VLC arguments as an array (safe from word-splitting)
build_vlc_args() {
    VLC_ARGS=(
        --no-osd
        --fullscreen
        "--image-duration=${PHOTO_DURATION}"
        --no-video-title-show
        --no-video-deco
        --autoscale
    )

    if [ "$SHUFFLE" = "yes" ]; then
        VLC_ARGS+=(--random)
    fi

    if [ "$LOOP" = "yes" ]; then
        VLC_ARGS+=(--loop)
    fi
}

# Generate playlist from media directory
generate_playlist() {
    echo "#EXTM3U" > "$PLAYLIST_FILE"
    find_media | sort >> "$PLAYLIST_FILE"
}

# Get hash of media files including sizes and mtimes for change detection
get_media_hash() {
    find_media | sort | xargs -r stat --format='%n %s %Y' 2>/dev/null | md5sum | awk '{print $1}'
}

# Count media files
count_media() {
    find_media | wc -l
}

# Show welcome screen with QR code when no media files are present
WELCOME_VLC_PID=""
show_welcome_screen() {
    kill_welcome_screen
    local welcome_img
    welcome_img="${SCRIPT_DIR}/static/welcome.png"

    # Generate welcome screen if it doesn't exist or IP changed
    if [ -x "${SCRIPT_DIR}/generate-welcome.sh" ]; then
        "${SCRIPT_DIR}/generate-welcome.sh" 2>/dev/null || true
    fi

    if [ -f "$welcome_img" ]; then
        cvlc --no-osd --fullscreen --no-video-title-show --image-duration=0 \
            --loop "$welcome_img" &
        WELCOME_VLC_PID=$!
        echo "$(date): Showing welcome screen with QR code"
    elif command -v zenity &>/dev/null; then
        local ip
        ip=$(get_ip)
        zenity --info --title="Pi Photo Display" \
            --text="No photos yet!\n\nOpen http://${ip:-photoframe.local}:8080\nto add photos from your phone." \
            --width=600 --no-wrap 2>/dev/null &
        WELCOME_VLC_PID=$!
    fi
}

kill_welcome_screen() {
    if [ -n "$WELCOME_VLC_PID" ] && kill -0 "$WELCOME_VLC_PID" 2>/dev/null; then
        kill "$WELCOME_VLC_PID" 2>/dev/null || true
        wait "$WELCOME_VLC_PID" 2>/dev/null || true
        WELCOME_VLC_PID=""
    fi
}

# Notify systemd watchdog (keeps service alive)
notify_watchdog() {
    if [ -n "${WATCHDOG_USEC:-}" ]; then
        systemd-notify WATCHDOG=1 2>/dev/null || true
    fi
}

# Get the Pi's IP address for display messages
get_ip() {
    hostname -I 2>/dev/null | awk '{print $1}'
}

# Start VLC
start_vlc() {
    generate_playlist

    local count
    count=$(count_media)
    if [ "$count" -eq 0 ]; then
        local ip
        ip=$(get_ip)
        echo "$(date): No media files found in $MEDIA_DIR. Waiting..."
        show_welcome_screen
        return 1
    fi

    kill_welcome_screen
    echo "$(date): Starting slideshow with $count files"
    build_vlc_args
    cvlc "${VLC_ARGS[@]}" "$PLAYLIST_FILE" &
    VLC_PID=$!
    VLC_START_TIME=$(date +%s)
    LAST_HASH=$(get_media_hash)
    echo "$(date): VLC started (PID $VLC_PID)"
    return 0
}

# Stop VLC with timeout and SIGKILL fallback
stop_vlc() {
    if [ -n "$VLC_PID" ] && kill -0 "$VLC_PID" 2>/dev/null; then
        echo "$(date): Stopping VLC (PID $VLC_PID)"
        kill "$VLC_PID" 2>/dev/null || true
        # Wait up to 5 seconds for graceful shutdown
        local i=0
        while [ $i -lt 50 ] && kill -0 "$VLC_PID" 2>/dev/null; do
            sleep 0.1
            i=$((i + 1))
        done
        # Force kill if still alive
        if kill -0 "$VLC_PID" 2>/dev/null; then
            echo "$(date): VLC did not stop gracefully, sending SIGKILL"
            kill -9 "$VLC_PID" 2>/dev/null || true
            wait "$VLC_PID" 2>/dev/null || true
        fi
        VLC_PID=""
    fi
}

# Handle signals - use background sleep so signals are caught immediately
cleanup() {
    echo "$(date): Shutting down slideshow..."
    stop_vlc
    kill_welcome_screen
    [ -n "$SLEEP_PID" ] && kill "$SLEEP_PID" 2>/dev/null || true
    rm -f "$PLAYLIST_FILE"
    exit 0
}

trap cleanup SIGTERM SIGINT SIGHUP

# --- Boot-time health checks ---

# Check 1: Filesystem read-only detection (common after unclean SD card shutdown)
check_filesystem_rw() {
    local test_file="${MEDIA_DIR}/.fs-write-test-$$"
    # First try to detect read-only mount
    if mount | grep -q "on / .*\bro\b"; then
        echo "$(date): CRITICAL: Root filesystem is mounted read-only!"
        echo "$(date): This usually happens after an unclean shutdown (power loss)"
        echo "$(date): Attempting to remount read-write..."
        if sudo mount -o remount,rw / 2>/dev/null; then
            echo "$(date): Successfully remounted root filesystem read-write"
        else
            echo "$(date): CRITICAL: Failed to remount root filesystem - system may be degraded"
        fi
    fi
    # Also test actual write capability to media directory
    mkdir -p "$MEDIA_DIR" 2>/dev/null || true
    if touch "$test_file" 2>/dev/null; then
        rm -f "$test_file"
    else
        echo "$(date): CRITICAL: Cannot write to $MEDIA_DIR - filesystem may be read-only or full"
        if sudo mount -o remount,rw / 2>/dev/null; then
            echo "$(date): Remounted root filesystem read-write"
        fi
    fi
}

check_filesystem_rw

# Check 2: Self-heal .env
heal_env_file

# Ensure media directory exists
mkdir -p "$MEDIA_DIR"

echo "$(date): Pi Photo Display slideshow starting"
echo "$(date): Media directory: $MEDIA_DIR"
echo "$(date): Photo duration: ${PHOTO_DURATION}s | Shuffle: $SHUFFLE | Auto-refresh: $AUTO_REFRESH"

# Disable screen blanking
export DISPLAY="${DISPLAY:-:0}"

# Wait for X11 display to become ready (up to 30 seconds).
# On boot the display server may not be available immediately.
if command -v xdpyinfo &>/dev/null; then
    X11_WAIT=0
    while ! xdpyinfo -display "$DISPLAY" &>/dev/null; do
        if [ "$X11_WAIT" -ge 30 ]; then
            echo "$(date): WARNING: X11 display $DISPLAY not ready after 30s, continuing anyway"
            break
        fi
        echo "$(date): Waiting for X11 display $DISPLAY to be ready..."
        sleep 2
        X11_WAIT=$((X11_WAIT + 2))
    done
    if [ "$X11_WAIT" -lt 30 ]; then
        echo "$(date): X11 display $DISPLAY is ready"
    fi
fi

xset s off 2>/dev/null || echo "$(date): NOTE: xset not available (normal on Wayland)"
xset -dpms 2>/dev/null || true
xset s noblank 2>/dev/null || true

# Main loop
while true; do
    # Start VLC if not running (with crash backoff)
    if [ -z "$VLC_PID" ] || ! kill -0 "$VLC_PID" 2>/dev/null; then
        # Detect rapid crashes (VLC died within 10 seconds of starting)
        # which usually indicates a corrupt media file
        if [ -n "$VLC_PID" ] && [ "$VLC_START_TIME" -gt 0 ]; then
            runtime=$(( $(date +%s) - VLC_START_TIME ))
            if [ "$runtime" -lt 10 ]; then
                CONSECUTIVE_FAILURES=$((CONSECUTIVE_FAILURES + 1))
                echo "$(date): VLC crashed after only ${runtime}s (failure $CONSECUTIVE_FAILURES/$MAX_FAILURES)"
            else
                CONSECUTIVE_FAILURES=0
            fi
        fi
        VLC_PID=""
        if [ "$CONSECUTIVE_FAILURES" -ge "$MAX_FAILURES" ]; then
            echo "$(date): VLC crashed $CONSECUTIVE_FAILURES times rapidly - quarantining suspect file"
            quarantine_latest_file
            echo "$(date): Backing off ${BACKOFF_SECONDS}s before retry..."
            sleep "$BACKOFF_SECONDS" &
            SLEEP_PID=$!
            wait "$SLEEP_PID" 2>/dev/null || true
            SLEEP_PID=""
            CONSECUTIVE_FAILURES=0
        fi
        if start_vlc; then
            # Reset only if VLC ran without "no media" (return 1)
            :
        else
            CONSECUTIVE_FAILURES=$((CONSECUTIVE_FAILURES + 1))
        fi
    fi

    # Check for new/modified files with debounce
    if [ "$AUTO_REFRESH" = "yes" ] && [ -n "$VLC_PID" ]; then
        current_hash=$(get_media_hash)
        if [ "$current_hash" != "$LAST_HASH" ]; then
            echo "$(date): Media change detected, waiting for stability..."
            sleep 5 &
            SLEEP_PID=$!
            wait "$SLEEP_PID" 2>/dev/null || true
            SLEEP_PID=""
            second_hash=$(get_media_hash)
            if [ "$current_hash" = "$second_hash" ]; then
                echo "$(date): Files stable, restarting slideshow..."
                stop_vlc
                sleep 1
                start_vlc || true
            else
                echo "$(date): Files still changing, deferring restart..."
                LAST_HASH="$current_hash"
            fi
        fi
    fi

    # Proactive VLC restart every 6 hours to prevent memory leak accumulation
    if [ -n "$VLC_PID" ] && kill -0 "$VLC_PID" 2>/dev/null && [ "$VLC_START_TIME" -gt 0 ]; then
        now_ts=$(date +%s)
        if [ $((now_ts - VLC_START_TIME)) -ge "$VLC_RESTART_INTERVAL" ]; then
            echo "$(date): MAINTENANCE: Proactive VLC restart after $((VLC_RESTART_INTERVAL / 3600)) hours (memory leak prevention)"
            stop_vlc
            sleep 2
            start_vlc || true
        fi
    fi

    # Memory watchdog: restart VLC if available memory is critically low
    if [ -n "$VLC_PID" ] && kill -0 "$VLC_PID" 2>/dev/null; then
        mem_avail=$(get_available_memory_mb)
        if [ "$mem_avail" -lt "$MIN_AVAILABLE_MB" ] 2>/dev/null; then
            echo "$(date): MEMORY: Available memory critically low (${mem_avail}MB < ${MIN_AVAILABLE_MB}MB threshold)"
            echo "$(date): MEMORY: Proactively restarting VLC to free memory before OOM killer"
            stop_vlc
            # Give kernel time to reclaim memory
            sleep 3
            mem_after=$(get_available_memory_mb)
            echo "$(date): MEMORY: After VLC stop: ${mem_after}MB available"
            start_vlc || true
        fi
    fi

    # Periodic self-test (hourly)
    run_selftest

    # Tell systemd we're alive
    notify_watchdog

    # Sleep in background so signals are handled immediately
    sleep "$REFRESH_INTERVAL" &
    SLEEP_PID=$!
    wait "$SLEEP_PID" 2>/dev/null || true
    SLEEP_PID=""
done
