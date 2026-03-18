# Contributing

Contributions are welcome! Here's how to help:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit your changes (`git commit -m 'Add my feature'`)
4. Push to the branch (`git push origin feature/my-feature`)
5. Open a Pull Request

## Development Setup

This project is designed to run on Raspberry Pi OS. For local development/testing of the web UI:

```bash
pip install flask
cd app
python web_upload.py
```

## Reporting Issues

Please include:
- Raspberry Pi model
- OS version (`cat /etc/os-release`)
- Steps to reproduce
- Relevant logs (`journalctl -u slideshow` or `journalctl -u photo-upload`)
