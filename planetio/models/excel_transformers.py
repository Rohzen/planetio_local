"""Helpers used while importing Excel/GeoJSON data."""

from typing import Any, Tuple


def _parse_pair(value: Any) -> Tuple[float | None, float | None]:
    """Parse a latitude/longitude pair from ``value``.

    The importer historically accepted values either as comma-separated
    strings (``"lat, lon"``) or as sequences.  The helper keeps that logic
    lightweight so the tests (and any custom transforms) can reuse it
    without loading the full Odoo environment.
    """

    if value in (None, ""):
        return None, None

    if isinstance(value, (list, tuple)):
        items = list(value)
    else:
        if not isinstance(value, str):
            return None, None
        # Normalize separators and drop empty chunks.
        normalized = value.replace(";", ",").replace("|", ",")
        items = [chunk.strip() for chunk in normalized.split(",") if chunk.strip()]

    if len(items) < 2:
        return None, None

    try:
        first = float(items[0])
        second = float(items[1])
    except (TypeError, ValueError):
        return None, None

    return first, second


__all__ = ["_parse_pair"]
