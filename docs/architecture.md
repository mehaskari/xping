# xping Architecture

## Design Principles

1. **Separation of concerns** — diagnostics, models, rendering, CLI are independent layers
2. **Stdlib first** — no external dependencies except `certifi`
3. **Fail gracefully** — every diagnostic falls back (raw socket → system ping, dig → raw UDP, port 43 → RDAP)
4. **Stream output** — each result printed immediately, never buffered
5. **Export everywhere** — every command supports `--json`, `--csv`, `--markdown`, `--output`

---

## Layer Architecture

```
┌─────────────────────────────────────────┐
│              CLI Layer                  │
│  main.py  parser.py  commands.py        │
│  export.py  completion.py               │
└────────────────┬────────────────────────┘
                 │ calls
┌────────────────▼────────────────────────┐
│           Diagnostics Layer             │
│  ping  trace  lookup  tcp  portscan     │
│  mtr  mtu  tls  http  whois  rdns       │
│  health  dnscheck  speedtest  listen    │
│  osdetect  profile  bundle  deps        │
└──────┬───────────────────┬─────────────┘
       │ produces          │ calls
┌──────▼──────┐    ┌───────▼─────────────┐
│   Models    │    │    Render Layer      │
│  dataclasses│    │  ansi  layout       │
│  + to_dict()│    │  latency  tables    │
└──────┬──────┘    │  progress  views/   │
       │           └─────────────────────┘
┌──────▼──────┐
│  Exporters  │
│  json csv md│
└─────────────┘
```

---

## Fallback Chain

### Ping
```
raw ICMP socket (needs root / cap_net_raw)
    ↓ no permission
system ping(8)
    ↓ not found
error + exit
```

### Traceroute / MTR
```
raw UDP + raw ICMP (needs root)
    ↓ no permission
system traceroute/tracert(8)
    ↓ not found
error + partial result
```

### DNS lookup
```
system dig(1) — supports custom server
    ↓ dig not found
raw UDP DNS packet to 8.8.8.8 (or --server)
```

### WHOIS
```
port 43 → IANA → registry → registrar (2 retries × 3s)
    ↓ timeout / blocked
RDAP HTTPS (certifi SSL, then unverified fallback)
    ↓ RDAP unavailable (.ir etc.)
error with helpful message
```

---

## Platform Support

| Feature | Linux | macOS | Windows |
|---------|-------|-------|---------|
| ping / trace | ✔ | ✔ | ✔ |
| ping --watch | ✔ | ✔ | ✔ |
| mtr | ✔ | ✔ | ⚠️ no tracert fallback |
| lookup --server | ✔ | ✔ | ✔ |
| tls | ✔ | ✔ | ✔ |
| http / HTTP/2 | ✔ | ✔ | ✔ |
| whois + RDAP | ✔ | ✔ | ✔ |
| portscan --banners | ✔ | ✔ | ✔ |
| mtu | ✔ | ✔ | ✔ |
| health + history | ✔ | ✔ | ✔ |
| speedtest | ✔ | ✔ | ✔ |
| listen | ✔ (ss) | ✔ (netstat) | ✔ (netstat) |
| osdetect | ✔ | ✔ | ✔ |
| completion | bash/zsh/fish | bash/zsh/fish | ⚠️ not PowerShell |
| export flags | ✔ | ✔ | ✔ |

---

## Testing Strategy

| Type | Location | Target |
|------|----------|--------|
| Unit — models | `tests/test_new_features.py` | `to_dict()` + computed properties |
| Unit — diagnostics | `tests/test_new_features.py` | logic only, network mocked |
| Unit — CLI | `tests/test_cli.py` | parser flags, dispatch |
| Unit — exporters | `tests/test_exporters.py` | JSON/CSV/Markdown |
| Platform commands | `tests/test_platform_cmds.py` | command builders per OS |
| Bundle | `tests/test_bundle.py` | all-in-one |

All network calls are mocked — no real network access in tests.
