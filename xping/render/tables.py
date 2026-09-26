"""Table rendering."""

from .ansi import BOLD, BRAND_INDIGO, BWHITE, COLOR, DIM, RESET, c, pad, visible_len


def print_table(
    headers: list[str], rows: list[list[str]], col_colors: list[str] | None = None
) -> None:
    """Print a neatly aligned table.

    Cells may already be coloured: widths and padding use the *visible*
    width, so colour codes never push a column out of line.
    """
    if not rows:
        return
    widths = [
        max(
            visible_len(str(h)),
            max((visible_len(str(r[i])) for r in rows if i < len(r)), default=0),
        )
        for i, h in enumerate(headers)
    ]

    def fmt_row(cells, is_header=False):
        parts = []
        for i, width in enumerate(widths):
            cell = str(cells[i]) if i < len(cells) else ""
            if is_header:
                cell = c(cell, BRAND_INDIGO, BOLD)
            elif col_colors and i < len(col_colors) and COLOR:
                cell = col_colors[i] + cell + RESET
            elif not cell.startswith("\033["):
                cell = c(cell, BWHITE)
            parts.append(pad(cell, width))
        bar = c("│", DIM)
        return f"  {bar} " + f" {bar} ".join(parts) + f" {bar}"

    def border(left: str, mid: str, right: str) -> str:
        return "  " + c(left + mid.join("─" * (w + 2) for w in widths) + right, DIM)

    print(border("┌", "┬", "┐"))
    print(fmt_row(headers, is_header=True))
    print(border("├", "┼", "┤"))
    for row in rows:
        print(fmt_row(row))
    print(border("└", "┴", "┘"))
