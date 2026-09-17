"""Local listening ports render view."""

from ..ansi import BOLD, BRAND_AMBER, BRAND_MINT, BRAND_TEAL, BWHITE, DIM, c
from ..tables import print_table


def print_result(result) -> None:
    if not result.entries:
        print(c("  No listening ports found.", DIM))
        print()
        return

    rows = []
    for e in result.entries:
        proto_color = BRAND_TEAL if e.proto == "tcp" else BRAND_AMBER
        port_str = c(str(e.local_port), BRAND_MINT, BOLD)
        proto_str = c(e.proto.upper(), proto_color)
        addr_str = c(e.local_addr, DIM)
        proc_str = c(e.process or "—", BWHITE) if e.process else c("—", DIM)
        pid_str = c(str(e.pid), DIM) if e.pid else c("—", DIM)
        rows.append([port_str, proto_str, addr_str, proc_str, pid_str])

    print_table(["Port", "Proto", "Address", "Process", "PID"], rows)
    print()
    print(c(f"  {result.count} listening port(s) found.", BRAND_MINT))
    print()
