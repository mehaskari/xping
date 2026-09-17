"""Table rendering."""

from .ansi import BOLD, BRAND_INDIGO, BWHITE, COLOR, DIM, RESET, c


def print_table(
    headers: list[str], rows: list[list[str]], col_colors: list[str] | None = None
) -> None:
    """Print a neatly aligned table."""
    if not rows:
        return
    widths = [
        max(len(str(h)), max(len(str(r[i])) for r in rows if i < len(r)))
        for i, h in enumerate(headers)
    ]

    def fmt_row(cells, is_header=False):
        parts = []
        for i, cell in enumerate(cells):
            w = widths[i] if i < len(widths) else 10
            padded = str(cell).ljust(w)
            if is_header:
                parts.append(c(padded, BRAND_INDIGO, BOLD))
            elif col_colors and i < len(col_colors):
                parts.append(col_colors[i] + padded + RESET if COLOR else padded)
            else:
                parts.append(c(padded, BWHITE))
        return "  " + c("│", DIM) + f"  {c('│', DIM)}  ".join(parts) + "  " + c("│", DIM)

    sep_inner = "  " + c("├" + "─┼─".join("─" * (w + 2) for w in widths) + "┤", DIM)
    sep_top = "  " + c("┌" + "─┬─".join("─" * (w + 2) for w in widths) + "┐", DIM)
    sep_bot = "  " + c("└" + "─┴─".join("─" * (w + 2) for w in widths) + "┘", DIM)

    print(sep_top)
    print(fmt_row(headers, is_header=True))
    print(sep_inner)
    for row in rows:
        print(fmt_row(row))
    print(sep_bot)
