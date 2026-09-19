# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.3.x   | ✅ Active |
| < 1.3   | ❌ No longer supported |

## Reporting a Vulnerability

Do not open public GitHub Issues for security vulnerabilities.

- **Preferred**: GitHub → Security → Advisories → New draft security advisory
- **Email**: iorganamis@gmail.com — subject `[xping] Security: <description>`

Include: description, reproduction steps, potential impact.

## Response Timeline

| Stage | Timeframe |
|-------|-----------|
| Acknowledgement | 48 hours |
| Fix (critical) | 7 days |
| Fix (others) | 30 days |

## Security Design

xping is a **read-only diagnostic tool**: no daemon, no server, no
stored credentials. Raw socket access is optional and falls back to
the system `ping` binary. `--output` file writes are opt-in with
user-supplied paths. No `eval`/`exec` anywhere.
