"""Tabular views of diagnostic results for CSV and Markdown export.

JSON keeps the full nested structure. CSV and Markdown are for
spreadsheets and reports, where a nested list crammed into one cell is
useless, so each result type declares its natural rows here: one row per
ping reply, per trace hop, per scanned port, and so on.

``sections_for(result)`` returns the tables; the first one is the primary
table (what CSV emits). ``summary_for(result)`` returns the scalar
top-level fields (what Markdown shows above the tables, and what CSV falls
back to for results without rows).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any

from .serialize import to_dict


@dataclass
class Section:
    title: str
    columns: list[str]
    rows: list[list[Any]] = field(default_factory=list)
    # False for side tables (HTTP headers, TLS SANs, …): CSV then exports the
    # summary fields instead, because those are the result's real payload.
    primary: bool = True


def _ms(value: float | None) -> float | str:
    return "" if value is None or value < 0 else round(value, 3)


def _hops_section(hops: list, title: str = "Hops") -> Section:
    width = max((len(h.rtts) for h in hops), default=0)
    columns = ["ttl", "ip", "host", "asn", "as_name", "avg_rtt_ms", "timeout"]
    columns += [f"probe_{i}_ms" for i in range(1, width + 1)]
    rows = []
    for h in hops:
        probes = [_ms(r) for r in h.rtts] + [""] * (width - len(h.rtts))
        rows.append(
            [
                h.ttl,
                h.ip or "",
                h.host or "",
                getattr(h, "asn", None) or "",
                getattr(h, "as_name", None) or "",
                _ms(h.avg_rtt),
                h.timeout,
                *probes,
            ]
        )
    return Section(title, columns, rows)


def _ping_section(r) -> Section:
    rows = [[i, _ms(rtt), "reply" if rtt >= 0 else "timeout"] for i, rtt in enumerate(r.rtts, 1)]
    return Section("Replies", ["seq", "rtt_ms", "status"], rows)


def _dns_section(r) -> Section:
    rows: list[list[Any]] = []
    rows += [["A", ip, "", r.reverse.get(ip, "")] for ip in r.ipv4]
    rows += [["AAAA", ip, "", r.reverse.get(ip, "")] for ip in r.ipv6]
    if r.cname:
        rows.append(["CNAME", r.cname, "", ""])
    rows += [["MX", host, prio, ""] for prio, host in r.mx]
    rows += [["NS", ns, "", ""] for ns in r.ns]
    rows += [["TXT", txt, "", ""] for txt in r.txt]
    return Section("Records", ["type", "value", "priority", "reverse"], rows)


def _tcp_section(r) -> Section:
    rows = [[a.seq, a.ok, _ms(a.elapsed_ms), a.error or ""] for a in r.attempts]
    return Section("Attempts", ["seq", "ok", "elapsed_ms", "error"], rows)


def sections_for(result: Any) -> list[Section]:
    """Tables for *result*, primary table first (empty if it has none)."""
    from xping import models as m

    if isinstance(result, list):
        if result and all(isinstance(h, m.Hop) for h in result):
            return [_hops_section(result)]
        return []
    if isinstance(result, m.PingResult):
        return [_ping_section(result)]
    if isinstance(result, m.TcpResult):
        return [_tcp_section(result)]
    if isinstance(result, m.DnsResult):
        return [_dns_section(result)]
    if isinstance(result, m.BlocklistResult):
        rows = [
            [ch.list_name, ch.zone, ch.subject, ch.status, " ".join(ch.codes), ch.reason]
            for ch in result.checks
        ]
        return [
            Section("Blocklists", ["list", "zone", "subject", "status", "codes", "reason"], rows)
        ]
    if isinstance(result, m.UdpResult):
        rows = [[a.seq, a.state, _ms(a.rtt_ms), a.reply_bytes, a.detail] for a in result.attempts]
        return [Section("Attempts", ["seq", "state", "rtt_ms", "reply_bytes", "detail"], rows)]
    if isinstance(result, m.NtpResult):
        rows = [[s.seq, s.offset_ms, s.delay_ms, s.error or ""] for s in result.samples]
        return [Section("Samples", ["seq", "offset_ms", "delay_ms", "error"], rows)]
    if isinstance(result, m.PortScanResult):
        rows = [
            [
                p.port,
                "open" if p.open else "closed",
                p.service or "",
                p.banner or "",
                _ms(p.elapsed_ms),
                p.error or "",
            ]
            for p in result.results
        ]
        return [
            Section("Ports", ["port", "state", "service", "banner", "elapsed_ms", "error"], rows)
        ]
    if isinstance(result, m.SweepResult):
        rows = [
            [h.ip, h.alive, " ".join(map(str, h.open_ports)), _ms(h.elapsed_ms)]
            for h in result.hosts
        ]
        return [Section("Hosts", ["ip", "alive", "open_ports", "elapsed_ms"], rows)]
    if isinstance(result, m.IpScanResult):
        rows = [
            [p.ip, p.alive, _ms(p.rtt_ms), _ms(p.elapsed_ms), p.error or ""] for p in result.probes
        ]
        return [Section("Hosts", ["ip", "alive", "rtt_ms", "elapsed_ms", "error"], rows)]
    if isinstance(result, m.MtrResult):
        columns = ["ttl", "ip", "host", "asn", "as_name", "loss_pct", "sent", "received"]
        columns += ["last_ms", "avg_ms", "best_ms", "worst_ms", "stdev_ms"]
        rows = [
            [
                h.ttl,
                h.ip or "",
                h.host or "",
                getattr(h, "asn", None) or "",
                getattr(h, "as_name", None) or "",
                round(h.loss_pct, 1),
                h.sent,
                h.received,
                _ms(h.last),
                _ms(h.avg),
                _ms(h.best),
                _ms(h.worst),
                round(h.stdev, 3),
            ]
            for h in result.hops
        ]
        return [Section("Hops", columns, rows)]
    if isinstance(result, m.HttpResult):
        requests = [[i, hop.url, hop.status_code] for i, hop in enumerate(result.redirects, 1)]
        if result.final_url or result.status_code is not None:
            requests.append([len(requests) + 1, result.final_url or result.url, result.status_code])
        headers = [[k, v] for k, v in result.headers.items()]
        security = [[h.name, h.status, h.value or "", h.note] for h in result.security]
        return [
            Section("Requests", ["step", "url", "status_code"], requests, primary=False),
            Section("Headers", ["name", "value"], headers, primary=False),
            Section(
                "Security headers", ["header", "status", "value", "note"], security, primary=False
            ),
        ]
    if isinstance(result, m.TlsResult):
        sans = [[n] for n in result.san]
        sections = [Section("Subject alternative names", ["name"], sans, primary=False)]
        if result.chain:
            sections.append(
                Section(
                    "Certificate chain",
                    ["position", "name"],
                    [list(pair) for pair in enumerate(result.chain)],
                    primary=False,
                )
            )
        return sections
    if isinstance(result, m.WhoisResult):
        rows = [["status", s] for s in result.status]
        rows += [["name_server", ns] for ns in result.name_servers]
        return [Section("Registry data", ["kind", "value"], rows, primary=False)]
    if isinstance(result, m.HealthResult):
        sections = [Section("Issues", ["issue"], [[i] for i in result.issues], primary=False)]
        if result.ping is not None:
            replies = _ping_section(result.ping)
            replies.primary = False
            sections.append(replies)
        return sections
    if isinstance(result, m.DnsCheckResult):
        rows = [[c.name, c.status, c.detail] for c in result.checks]
        return [Section("Checks", ["check", "status", "detail"], rows)]
    if isinstance(result, m.MtuResult):
        rows = [[p.get("size"), p.get("ok")] for p in result.probes]
        return [Section("Probes", ["payload_bytes", "ok"], rows)]
    if isinstance(result, m.ListenResult):
        rows = [
            [e.proto, e.local_addr, e.local_port, e.pid or "", e.process or ""]
            for e in result.entries
        ]
        return [Section("Listening sockets", ["proto", "address", "port", "pid", "process"], rows)]
    if isinstance(result, m.NetResult):
        rows = [
            [i.name, i.state, i.mtu or "", i.mac or "", " ".join(i.addresses)]
            for i in result.interfaces
        ]
        columns = ["interface", "state", "mtu", "mac", "addresses"]
        dns = [[s] for s in result.dns_servers]
        return [
            Section("Interfaces", columns, rows, primary=False),
            Section("DNS servers", ["server"], dns, primary=False),
        ]
    if isinstance(result, m.PropagationResult):
        columns = ["resolver", "server", "status", "records", "elapsed_ms"]
        if result.expected:
            columns.append("matches")
        rows = []
        for a in result.answers:
            row = [a.resolver, a.server or "system", a.status, " ".join(a.records), a.elapsed_ms]
            if result.expected:
                row.append(result.matches(a))
            rows.append(row)
        return [Section("Resolvers", columns, rows)]
    if isinstance(result, m.DoctorResult):
        rows = [
            [s.key, s.name, s.status, s.detail, s.hint, _ms(s.elapsed_ms)] for s in result.steps
        ]
        return [Section("Steps", ["step", "name", "status", "detail", "hint", "elapsed_ms"], rows)]
    if isinstance(result, m.CheckReport):
        rows = [[o.name, o.type, o.target, o.ok, o.detail, o.elapsed_ms] for o in result.outcomes]
        columns = ["name", "type", "target", "ok", "detail", "elapsed_ms"]
        return [Section("Checks", columns, rows)]
    if isinstance(result, m.ProfileListResult):
        rows = [[p.name, p.target, p.port or "", p.note or ""] for p in result.profiles]
        return [Section("Profiles", ["name", "target", "port", "note"], rows)]
    if isinstance(result, m.BundleResult):
        sections = []
        if result.lookup is not None:
            sections.append(_dns_section(result.lookup))
        if result.ping is not None:
            sections.append(_ping_section(result.ping))
        if result.trace:
            sections.append(_hops_section(result.trace, "Traceroute"))
        for t in result.tcp:
            section = _tcp_section(t)
            section.title = f"TCP {t.port}"
            sections.append(section)
        return sections
    return []


def summary_for(result: Any) -> list[tuple[str, Any]]:
    """Scalar top-level fields (and scalar computed properties) of *result*."""
    if not is_dataclass(result) or isinstance(result, type):
        return []
    data = result.to_dict() if hasattr(result, "to_dict") else to_dict(result)
    names = [f.name for f in fields(result)] + [
        k for k in data if k not in {f.name for f in fields(result)}
    ]
    return [(k, data[k]) for k in names if k in data and not isinstance(data[k], (list, dict))]


def cell(value: Any) -> str:
    """Render one table cell: JSON for nested data, empty string for None."""
    if value is None:
        return ""
    if isinstance(value, (list, dict, tuple)):
        return json.dumps(value, separators=(",", ":"))
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".") or "0"
    return str(value)
