# xping

**Network diagnostics for the terminal**: ping, traceroute, DNS, TLS,
HTTP, mail servers, Wi-Fi and more, behind one consistent command line with
readable output, meaningful exit codes and JSON / CSV / Markdown export.

```bash
pipx install xping
xping doctor          # why is the internet not working?
```

## Where to go

- **[User Guide](guide.md)**: every command and option, how to read the
  output, check files, recipes, privacy and a FAQ.
- **[Changelog](changelog.md)**: what changed in each release.
- **[Source and issues](https://github.com/mehaskari/xping)** on GitHub.

## A few starting points

| Task | Command |
|------|---------|
| Diagnose a broken connection | [`xping doctor`](guide.md#xping-doctor) |
| Is a host reachable, and how fast? | [`xping ping`](guide.md#xping-ping), [`xping tcp`](guide.md#xping-tcp) |
| Where does the path break? | [`xping trace --tcp`](guide.md#xping-trace), [`xping mtr`](guide.md#xping-mtr) |
| Why is a website slow? | [`xping http`](guide.md#xping-http) |
| Is my mail set up right? | [`xping dnscheck`](guide.md#xping-dnscheck), [`xping smtp`](guide.md#xping-smtp), [`xping blocklist`](guide.md#xping-blocklist) |
| How good is my Wi-Fi? | [`xping wifi`](guide.md#xping-wifi) |
| Did it get worse? | [`xping diff`](guide.md#xping-diff), [`xping history`](guide.md#xping-history), [`xping report`](guide.md#xping-report) |
| Many checks, one exit code | [`xping check`](guide.md#xping-check) |
| Watch everything that matters, live | [`xping monitor`](guide.md#xping-monitor) |
