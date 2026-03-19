# Contributing

Contributions are welcome. Here's how to help:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit your changes (`git commit -m 'Add my feature'`)
4. Push to the branch (`git push origin feature/my-feature`)
5. Open a Pull Request

## Development Setup

### Prerequisites

- Node.js 18+ (frontend build)
- Python 3.11+ with pip (backend)
- Docker (OS image build only)

### Frontend

FrameCast uses [Preact](https://preactjs.com/) + [esbuild](https://esbuild.github.io/) + [superhot-ui](https://www.npmjs.com/package/superhot-ui).

```bash
cd app/frontend
npm install
npm run dev      # watch mode with sourcemaps
npm run build    # production build → app/static/
```

### Backend

```bash
pip install flask gunicorn pillow
cd app
gunicorn -c gunicorn.conf.py web_upload:app
```

Open `http://localhost:8080` to test the phone UI. The kiosk (`/display`) requires a Wayland compositor — test visually on a Pi.

### Building the OS Image

The flashable `.img.xz` is built with [pi-gen](https://github.com/RPi-Distro/pi-gen) in Docker. This requires Docker and takes 20–60 minutes.

```bash
cd pi-gen
bash build.sh
```

Output lands in `pi-gen/deploy/`. The build script clones pi-gen at the pinned commit, applies the `stage2-framecast` custom stage, then compresses the image.

### CI/CD

- **Pull requests** trigger lint (ruff) and frontend build checks (`.github/workflows/test.yml`)
- **Tag pushes** (`v*`) build the OS image via pi-gen Docker (`.github/workflows/build-image.yml`)
- **Releases** are created automatically with the image and SHA256 checksum (`.github/workflows/release.yml`)

To test a tag build locally, push a `v*` tag to a fork.

## Reporting Issues

Please include:

- Raspberry Pi model
- FrameCast version (`cat /etc/framecast/VERSION`)
- Steps to reproduce
- Relevant logs:
  - `journalctl -u framecast` (web server)
  - `journalctl -u framecast-kiosk` (display)
  - `journalctl -u wifi-manager` (WiFi provisioning)
