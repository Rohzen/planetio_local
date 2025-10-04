"""Geospatial helpers used during data imports."""

from __future__ import annotations

import json
import math
from typing import Iterable, List, Sequence, Tuple

try:  # pragma: no cover - optional dependency
    from pyproj import CRS, Transformer  # type: ignore
except Exception:  # pragma: no cover - pyproj may not be available in tests
    CRS = None  # type: ignore
    Transformer = None  # type: ignore


Point = Tuple[float, float]
Ring = List[Point]
Polygon = List[Ring]


def _safe_load_geojson(payload: object) -> object | None:
    """Return a parsed GeoJSON object from ``payload`` if possible."""

    if payload in (None, "", b""):
        return None

    if isinstance(payload, (bytes, bytearray)):
        try:
            payload = payload.decode("utf-8")
        except Exception:
            return None

    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except Exception:
            return None

    if isinstance(payload, dict):
        return payload

    return None


def _iter_geometries(obj: object) -> Iterable[dict]:
    """Yield raw geometry dictionaries from GeoJSON containers."""

    if not isinstance(obj, dict):
        return

    gtype = obj.get("type")

    if gtype in {
        "Point",
        "Polygon",
        "MultiPolygon",
        "MultiPoint",
        "LineString",
        "MultiLineString",
    }:
        yield obj
        return

    if gtype == "Feature":
        geom = obj.get("geometry")
        if isinstance(geom, dict):
            yield from _iter_geometries(geom)
        return

    if gtype == "FeatureCollection":
        for feature in obj.get("features") or []:
            if isinstance(feature, dict):
                yield from _iter_geometries(feature.get("geometry"))
        return

    if gtype == "GeometryCollection":
        for geom in obj.get("geometries") or []:
            if isinstance(geom, dict):
                yield from _iter_geometries(geom)


def _normalise_ring(coords: Sequence[Sequence[float]]) -> Ring:
    """Return a cleaned ring of ``(lon, lat)`` pairs."""

    ring: Ring = []
    for pt in coords or []:
        if not isinstance(pt, (list, tuple)) or len(pt) < 2:
            continue
        try:
            lon = float(pt[0])
            lat = float(pt[1])
        except Exception:
            continue
        ring.append((lon, lat))

    if len(ring) < 3:
        return []

    if ring[0] != ring[-1]:
        ring.append(ring[0])

    return ring


def _collect_polygons(geom: dict) -> List[Polygon]:
    """Extract polygons (as rings) from a GeoJSON geometry dict."""

    polygons: List[Polygon] = []
    gtype = geom.get("type")
    coords = geom.get("coordinates")

    if gtype == "Polygon" and isinstance(coords, list):
        rings: Polygon = []
        for ring_coords in coords:
            ring = _normalise_ring(ring_coords)
            if ring:
                rings.append(ring)
        if rings:
            polygons.append(rings)

    elif gtype == "MultiPolygon" and isinstance(coords, list):
        for poly_coords in coords:
            rings: Polygon = []
            for ring_coords in poly_coords or []:
                ring = _normalise_ring(ring_coords)
                if ring:
                    rings.append(ring)
            if rings:
                polygons.append(rings)

    return polygons


def _project_points_to_meters(lonlat_list: Ring) -> Ring:
    """Project ``(lon, lat)`` pairs to metres (UTM when available)."""

    if not lonlat_list:
        return []

    lon0 = sum(p[0] for p in lonlat_list) / len(lonlat_list)
    lat0 = sum(p[1] for p in lonlat_list) / len(lonlat_list)

    if Transformer and CRS:
        try:
            zone = int(math.floor((lon0 + 180.0) / 6.0) + 1)
            north = lat0 >= 0.0
            epsg = 32600 + zone if north else 32700 + zone
            transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
            projected = [transformer.transform(lon, lat) for lon, lat in lonlat_list]
            return projected
        except Exception:  # pragma: no cover - fall back to local projection
            pass

    R = 6371008.8
    lat0_rad = math.radians(lat0)
    x0 = R * math.radians(lon0) * math.cos(lat0_rad)
    y0 = R * math.radians(lat0)
    projected: Ring = []
    for lon, lat in lonlat_list:
        x = R * math.radians(lon) * math.cos(lat0_rad)
        y = R * math.radians(lat)
        projected.append((x - x0, y - y0))
    return projected


def _shoelace_area(coords_xy: Ring) -> float:
    """Return planar polygon area via the shoelace formula."""

    if len(coords_xy) < 3:
        return 0.0

    area = 0.0
    n = len(coords_xy)
    for i in range(n - 1):
        x1, y1 = coords_xy[i]
        x2, y2 = coords_xy[i + 1]
        area += x1 * y2 - x2 * y1

    return abs(area) * 0.5


def _polygon_area_m2(polygons: List[Polygon]) -> float:
    """Compute area in square metres for the provided polygons."""

    total = 0.0
    for rings in polygons:
        if not rings:
            continue

        exterior = _project_points_to_meters(rings[0])
        area = _shoelace_area(exterior)

        for hole in rings[1:]:
            hole_xy = _project_points_to_meters(hole)
            area -= _shoelace_area(hole_xy)

        if area > 0.0:
            total += area

    return total


def _count_points(geom: dict) -> int:
    """Return the number of points represented by a geometry."""

    gtype = geom.get("type")
    coords = geom.get("coordinates")

    def _is_point(pt: object) -> bool:
        return isinstance(pt, (list, tuple)) and len(pt) >= 2

    if gtype == "Point" and _is_point(coords):
        return 1

    if gtype == "MultiPoint" and isinstance(coords, list):
        return sum(1 for pt in coords if _is_point(pt))

    return 0


def _get_min_point_area_ha(env, default: float = 4.0) -> float:
    """Fetch the minimum area per point from configuration."""

    if env is None:
        return default

    try:
        icp = env["ir.config_parameter"].sudo()
        value = icp.get_param("planetio.gfw_min_area_ha", default=str(default))
        if value in (None, ""):
            return default
        return max(float(value), 0.0)
    except Exception:  # pragma: no cover - defensive
        return default


def estimate_geojson_area_ha(env, geometry, min_point_area_ha: float | None = None) -> float:
    """Estimate the area in hectares represented by ``geometry``."""

    gobj = _safe_load_geojson(geometry)
    if not gobj:
        return 0.0

    polygons: List[Polygon] = []
    point_count = 0

    for geom in _iter_geometries(gobj):
        polygons.extend(_collect_polygons(geom))
        point_count += _count_points(geom)

    area_m2 = 0.0

    if polygons:
        area_m2 += _polygon_area_m2(polygons)

    if point_count:
        if min_point_area_ha is None:
            min_point_area_ha = _get_min_point_area_ha(env)
        per_point = max(float(min_point_area_ha or 0.0), 0.0)
        area_m2 += point_count * per_point * 10000.0

    return (area_m2 / 10000.0) if area_m2 > 0.0 else 0.0


__all__ = ["estimate_geojson_area_ha"]

