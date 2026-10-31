"""Small utilities shared by the repository's Matplotlib figure scripts."""

from __future__ import annotations

from pathlib import Path


def normalize_svg_whitespace(path: Path) -> None:
    """Remove Matplotlib's trailing spaces from wrapped SVG path commands."""
    svg_path = Path(path)
    source = svg_path.read_text(encoding="utf-8")
    normalized = "\n".join(line.rstrip() for line in source.splitlines()) + "\n"
    if source != normalized:
        svg_path.write_bytes(normalized.encode("utf-8"))
