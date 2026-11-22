"""Plain-text table rendering. No dependencies, no colour assumptions."""

from __future__ import annotations


def table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "  (nothing found)"
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    lines = ["  " + "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)).rstrip()]
    lines.append("  " + "  ".join("-" * widths[i] for i in range(len(headers))))
    for row in rows:
        lines.append("  " + "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
    return "\n".join(lines)


def shorten(text: str | None, width: int) -> str:
    if not text:
        return "-"
    return text if len(text) <= width else text[: width - 1] + "\u2026"
