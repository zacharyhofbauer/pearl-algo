#!/usr/bin/env python3
# ============================================================================
# Category: Testing/Validation
# Purpose: Generate a simple coverage badge SVG from coverage.xml
# Usage: python3 scripts/testing/generate_coverage_badge.py
# ============================================================================

from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET


def _coverage_color(pct: int) -> str:
    if pct >= 90:
        return "#4c1"  # brightgreen
    if pct >= 80:
        return "#97CA00"  # green
    if pct >= 70:
        return "#a4a61d"  # yellowgreen
    if pct >= 60:
        return "#dfb317"  # yellow
    if pct >= 50:
        return "#fe7d37"  # orange
    return "#e05d44"  # red


def _render_svg(label: str, value: str, color: str) -> str:
    # Minimal shields-style SVG (static, no external deps).
    label_width = 60
    value_width = 50
    total_width = label_width + value_width
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="20" role="img"'
        f' aria-label="{label}: {value}">'
        f'<linearGradient id="s" x2="0" y2="100%">'
        f'<stop offset="0" stop-color="#bbb" stop-opacity=".1"/>'
        f'<stop offset="1" stop-opacity=".1"/>'
        f'</linearGradient>'
        f'<clipPath id="r"><rect width="{total_width}" height="20" rx="3" fill="#fff"/></clipPath>'
        f'<g clip-path="url(#r)">'
        f'<rect width="{label_width}" height="20" fill="#555"/>'
        f'<rect x="{label_width}" width="{value_width}" height="20" fill="{color}"/>'
        f'<rect width="{total_width}" height="20" fill="url(#s)"/>'
        f'</g>'
        f'<g fill="#fff" text-anchor="middle"'
        f' font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">'
        f'<text x="{label_width / 2}" y="14">{label}</text>'
        f'<text x="{label_width + value_width / 2}" y="14">{value}</text>'
        f'</g>'
        f'</svg>'
    )


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    xml_path = repo_root / "coverage.xml"
    badge_path = repo_root / "docs" / "coverage-badge.svg"

    if not xml_path.exists():
        raise SystemExit("coverage.xml not found. Run pytest with --cov-report=xml first.")

    tree = ET.parse(xml_path)
    root = tree.getroot()
    line_rate = float(root.attrib.get("line-rate", "0") or 0)
    pct = int(round(line_rate * 100))
    color = _coverage_color(pct)

    badge_path.parent.mkdir(parents=True, exist_ok=True)
    badge_path.write_text(_render_svg("coverage", f"{pct}%", color), encoding="utf-8")
    print(f"Coverage badge written: {badge_path} ({pct}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
