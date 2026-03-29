# Contributing to FrameCast

Contributions are welcome. This document covers architecture, development setup, and PR guidelines.

---

## Architecture Overview

FrameCast is a single Flask application serving two distinct surfaces through one HTTP server (gunicorn, single worker):

- **Phone surface** -- Preact SPA for upload, settings, albums, favorites, stats, map, users, and OTA updates
- **TV surface** -- Preact slideshow with CSS transitions, boot sequence, and QR codes rendered in a Wayland kiosk (cage + GTK-WebKit)

### Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11+ (Flask + gunicorn) |
| Frontend | Preact + esbuild + superhot-ui (green phosphor variant) |
| Database | SQLite (WAL mode, single writer lock) |
| Real-time | Server-Sent Events (SSE) |
| Display | Wayland kiosk (cage compositor + GTK-WebKit) |
| Network | NetworkManager (nmcli) for WiFi provisioning |
| OS Image | pi-gen (Raspberry Pi OS Bookworm, arm64) |
| CI/CD | GitHub Actions |

### Key Modules

| Module | Responsibility |
|--------|---------------|
| `web_upload.py` | Flask app factory, upload handler, SPA routes |
| `api.py` | JSON API endpoints, rate limiting middleware |
| `sse.py` | SSE client management, event coalescing, reconnection |
| `modules/auth.py` | PIN authentication, cookie auth, Origin validation |
| `modules/config.py` | .env file read/write with atomic writes |
| `modules/db.py` | SQLite content model, migrations, CRUD |
| `modules/media.py` | Image processing, GPS extraction, disk usage |
| `modules/rotation.py` | Weighted slideshow playlist generation |
| `modules/updater.py` | OTA updates via GitHub Releases API |
| `modules/wifi.py` | WiFi scan, connect, AP mode via nmcli |

---

## Directory Structure

```
framecast/
|-- app/
|   |-- web_upload.py            # Entry point
|   |-- api.py                   # REST API + rate limiting
|   |-- sse.py                   # Server-Sent Events
|   |-- gunicorn.conf.py         # Gunicorn config (workers=1 mandatory)
|   |-- .env.example             # Default configuration
|   |-- modules/                 # Python modules
|   |-- frontend/
|   |   |-- src/
|   |   |   |-- display/         # TV surface (Slideshow.jsx)
|   |   |   |-- pages/           # Phone pages (Upload, Settings, etc.)
|   |   |   |-- components/      # Shared components (PhotoCard, Lightbox)
|   |   |-- esbuild.config.js
|   |-- static/                  # Built assets (gitignored dist/)
|   |-- templates/               # HTML shell templates
|-- pi-gen/
|   |-- build.sh                 # Image build orchestrator
|   |-- config                   # pi-gen variables
|   |-- stage2-framecast/
|   |   |-- 00-packages/         # APT package list
|   |   |-- 01-config/           # Boot config (cmdline.txt, config.txt)
|   |   |-- 02-app/              # App install + chroot setup
|   |   |-- 03-system/           # System hardening (journal, watchdog, ufw)
|-- scripts/
|   |-- health-check.sh          # Post-update health validation
|   |-- hdmi-control.sh          # HDMI-CEC wrapper
|   |-- smoke-test.sh            # Post-install validation
|-- systemd/                     # Service and timer units
|-- tests/                       # Python tests
|-- VERSION                      # Semver version string
```

---

## Development Setup

### Prerequisites

- Node.js 18+ and npm
- Python 3.11+ with pip
- Docker (only for OS image builds)

### Clone and Install

```bash
git clone https://github.com/parthalon025/framecast.git
cd framecast
```

### Frontend

```bash
cd app/frontend
npm install
npm run dev      # Watch mode with sourcemaps
npm run build    # Production build to app/static/
```

### Backend

```bash
pip install flask gunicorn pillow
cd app
cp .env.example .env
gunicorn -c gunicorn.conf.py web_upload:app
```

Open `http://localhost:8080` for the phone UI. The TV display (`/display`) works in any browser but is designed for the kiosk environment.

### Running Tests

```bash
cd tests
python -m pytest -x -q
```

### Building the OS Image

```bash
cd pi-gen
bash build.sh
```

Requires Docker. Output: `pi-gen/deploy/*.img.xz`. Takes 20-60 minutes.

---

## PR Guidelines

### Process

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes
4. Run tests and verify the frontend builds
5. Commit with a clear message (see below)
6. Push and open a Pull Request

### Rules

- **One feature per PR.** Keep PRs focused. A bugfix and a feature are two PRs.
- **Tests required.** New backend logic needs tests. Frontend changes need manual verification on a Pi or browser.
- **No breaking API changes** without a migration path.
- **gunicorn workers=1 is mandatory.** SSE, CEC, and stats buffering are process-singletons.

### Commit Messages

Use conventional commit format:

```
feat: add album sorting
fix: handle corrupt EXIF in GPS extraction
docs: update API endpoint documentation
chore: upgrade esbuild to 0.21
```

---

## superhot-ui Design Rules

FrameCast uses the **green phosphor monitor variant** (`data-sh-monitor="green"` on the layout root). All frontend work must follow these rules.

### Voice (piOS)

All UI text follows terminal system voice. No conversational language.

| Do | Do not |
|----|--------|
| `STANDBY` | "Loading..." |
| `FAULT` or `ERROR` | "Something went wrong" |
| `NO DATA` | "Nothing here yet" |
| `COMPLETE` | "Successfully completed!" |
| `CONFIRM: DELETE PHOTO?` | "Are you sure you want to delete?" |
| `[CONFIRM]` / `[CANCEL]` | "Yes" / "No" |
| `14:23:07` (24-hour) | "2:23 PM" |
| `2026-03-16` (ISO) | "March 16, 2026" |

### Components

Use superhot-ui components instead of building custom:

- `ShNav` for phone navigation (bottom bar)
- `ShModal` for modals and confirms (has built-in focus trap)
- `ShToast` for notifications
- `ShCollapsible` for settings sections
- `ShSkeleton` for loading states
- `ShDataTable` for data tables
- `ShErrorState` for error pages

### Layout

- CSS Grid with explicit columns (not flexbox wrapping)
- 60%+ void space
- `--space-*` tokens for all spacing
- Sharp corners, no organic curves
- Progressive disclosure: summary, then detail, then raw data

### Animation

- Silence = healthy (no idle animation)
- Max 3 simultaneous animated effects per viewport
- `prefers-reduced-motion` support mandatory
- Disable CRT effects on mobile

### Color

- Red = threat only (errors, DLQ). Never decorative red.
- Phosphor cyan = alive/emphasis. Never combine with red on same element.
- Hover: phosphor left-border reveal, not background color change

---

## Code Conventions

### Python

- All `except` blocks must log before returning a fallback value
- All SQLite access via `contextlib.closing()`
- All file writes use atomic pattern (write to `.tmp`, fsync, rename)
- `PRAGMA journal_mode=WAL` + `busy_timeout=5000` on every DB connection
- Toggle operations use atomic SQL (`UPDATE SET x = NOT x`)
- DB row INSERT before file write, not after
- Subprocess `kill()`/`terminate()` wrapped in `suppress(ProcessLookupError)`

### JavaScript/JSX

- Never use `h` as a callback parameter name (esbuild injects `h` as JSX factory -- shadowing it causes silent render crashes)
- Use descriptive callback parameter names (e.g., `photo`, `item`, `entry`)
- No emoji in UI text

### General

- Atomic writes everywhere -- power loss is the normal failure mode on Pi
- Log at appropriate levels: ERROR for failures, WARNING for degraded state, INFO for operations
- Secrets in env vars, never in code

---

## Reporting Issues

Please include:

- Raspberry Pi model
- FrameCast version (`cat /opt/framecast/VERSION`)
- Steps to reproduce
- Relevant logs:
  - `journalctl -u framecast` (web server)
  - `journalctl -u framecast-kiosk` (display)
