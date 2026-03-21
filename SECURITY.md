# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in FrameCast, please report it privately rather than opening a public issue.

**Email:** parthalon025@gmail.com
**Subject prefix:** `[SECURITY] FrameCast:`

Please include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

You will receive a response within 72 hours. Security fixes are prioritized over all other work.

## Supported Versions

| Version | Supported |
|---------|-----------|
| 2.0.x   | Yes       |
| < 2.0   | No        |

## Scope

FrameCast is designed as a **LAN-only appliance** — it is not intended to be exposed to the public internet. Security reports should be evaluated in this context. That said, we take all reports seriously, especially:

- Authentication bypass
- Unauthorized file access
- Code injection (SQL, command, XSS)
- Data exposure (EXIF GPS, credentials)
