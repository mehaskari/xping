# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.3.x   | ✅ Active |
| 1.2.x   | ⚠️ Critical fixes only |
| < 1.2   | ❌ No longer supported |

## Reporting a Vulnerability

**Do not open public GitHub Issues for security vulnerabilities.**

### Option 1 — GitHub Private Advisory (preferred)
**Security → Advisories → New draft security advisory**

### Option 2 — Email
**iorganamis@gmail.com** — subject: `[xping] Security: <description>`

Include: description, reproduction steps, potential impact, suggested mitigations.

## Response Timeline

| Stage | Timeframe |
|-------|-----------|
| Acknowledgement | 48 hours |
| Severity assessment | 5 days |
| Fix (critical) | 7 days |
| Fix (others) | 30 days |
| Public disclosure | After fix released |

## Security Design

xping is a **read-only diagnostic tool**:
- No credentials stored, no daemon, no server
- Raw socket access is optional — falls back to system `ping`
- `--output` writes are opt-in and user-supplied
- No `eval` or `exec`
- Inputs validated before passing to system tools
