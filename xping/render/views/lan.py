"""Local network device discovery rendering (xping lan)."""

from ..ansi import BOLD, BRAND_AMBER, BRAND_MINT, BRAND_ROSE, BRAND_TEAL, BWHITE, DIM, c
from ..tables import print_table


def _role(device) -> str:
    roles = []
    if device.is_self:
        roles.append(c("this machine", BRAND_TEAL, BOLD))
    if device.is_gateway:
        roles.append(c("router", BRAND_AMBER, BOLD))
    if device.random_mac:
        roles.append(c("private MAC", DIM))
    return ", ".join(roles)


def print_result(result) -> None:
    print()
    if result.error:
        print(c(f"  ✘ {result.error}", BRAND_ROSE, BOLD))
        print()
        return
    if not result.devices:
        print(c("  No devices answered.", DIM))
        print()
        return
    rows = [
        [
            c(d.ip, BWHITE, BOLD),
            c(d.mac or "—", DIM),
            d.vendor or c("—", DIM),
            d.name or c("—", DIM),
            _role(d),
        ]
        for d in result.devices
    ]
    print_table(["IP", "MAC", "Vendor", "Name", ""], rows)
    print()
    where = f" on {result.interface}" if result.interface else ""
    print(c(f"  {result.count} device(s) on {result.network}{where}.", BRAND_MINT))
    if result.vendor_db is None:
        print(
            c(
                "  Vendors need a MAC prefix list: install nmap or Wireshark "
                "(or ieee-data / hwdata on Linux).",
                DIM,
            )
        )
    if any(d.random_mac for d in result.devices):
        print(
            c(
                "  A private MAC is randomised or locally assigned (phones, laptops,"
                " range extenders), so it names no vendor.",
                DIM,
            )
        )
    if not result.scanned:
        print(c("  Without a scan, only devices this machine talked to recently are listed.", DIM))
    print()
