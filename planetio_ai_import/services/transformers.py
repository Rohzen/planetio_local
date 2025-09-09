from odoo import models
import json, re

def _to_float(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int,float)):
        return float(v)
    s = str(v).strip().replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None

def _assert_lat_lon(lat, lon):
    if lat is None or lon is None:
        raise ValueError("Missing lat/lon")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError(f"Out of range lat/lon: {lat},{lon}")

_pair_re = re.compile(r"^\s*([\-+0-9.,°'\" ]+)[,; ]+([\-+0-9.,°'\" ]+)\s*$")

def _dms_to_dd(s):
    parts = re.findall(r"[-+]?\d+(?:[.,]\d+)?", s or "")
    if not parts:
        return None
    nums = [float(p.replace(",", ".")) for p in parts]
    if len(nums) == 1:
        return nums[0]
    deg = nums[0]; mins = nums[1] if len(nums) > 1 else 0.0; secs = nums[2] if len(nums) > 2 else 0.0
    sign = -1 if str(s).strip().startswith("-") else 1
    return sign * (abs(deg) + mins/60.0 + secs/3600.0)

def _parse_dd_or_dms(s):
    f = _to_float(s)
    return f if f is not None else _dms_to_dd(str(s))

def _parse_pair(val):
    m = _pair_re.match(str(val))
    if not m:
        return None, None
    a = _parse_dd_or_dms(m.group(1))
    b = _parse_dd_or_dms(m.group(2))
    return a, b

class ExcelTransformers(models.AbstractModel):
    _name = "excel.import.transformers"
    _description = "Excel Import Transformers"

    def geo_point(self, row, lat_key, lon_key):
        lat = _parse_dd_or_dms(row.get(lat_key))
        lon = _parse_dd_or_dms(row.get(lon_key))
        # inversione automatica se serve
        if lat is not None and abs(lat) > 90:
            lat, lon = lon, lat
        _assert_lat_lon(lat, lon)
        return json.dumps({"type": "Point", "coordinates": [lon, lat]})

    def geo_polygon_from_columns(self, row, coord_cols):
        """
        Raccoglie coordinate da:
          - colonne "COORDINATES n" in forma "lat, lon" o "lon; lat" (anche DMS)
          - colonne LAT n / LON n (accoppiate per indice)
        Fallback:
          - >=3 coppie -> Polygon
          - 1-2 coppie -> Point (prima coppia valida)
          - 0 coppie -> None
        Ritorna: dict {"type": "polygon"|"point"|None, "geometry": <json str> or None}
        """
        coords = []
        lat_buf, lon_buf = None, None

        for k in coord_cols:
            val = row.get(k)
            label = (k or "").lower()
            if val in (None, ""):
                continue

            if re.search(r"(?i)\bcoordinates?\b", k or ""):
                a, b = _parse_pair(val)
                if a is None or b is None:
                    continue
                lat, lon = (a, b) if abs(a) <= 90 and abs(b) <= 180 else (b, a)
                _assert_lat_lon(lat, lon)
                coords.append([lon, lat])
            elif re.search(r"(?i)\b(lat|latitude)\b", label):
                lat_buf = _parse_dd_or_dms(val)
                if lon_buf is not None and lat_buf is not None:
                    lat, lon = lat_buf, lon_buf
                    if abs(lat) > 90: lat, lon = lon, lat
                    _assert_lat_lon(lat, lon)
                    coords.append([lon, lat])
                    lat_buf, lon_buf = None, None
            elif re.search(r"(?i)\b(lon|longitude)\b", label):
                lon_buf = _parse_dd_or_dms(val)
                if lon_buf is not None and lat_buf is not None:
                    lat, lon = lat_buf, lon_buf
                    if abs(lat) > 90: lat, lon = lon, lat
                    _assert_lat_lon(lat, lon)
                    coords.append([lon, lat])
                    lat_buf, lon_buf = None, None

        # Decide output
        if len(coords) >= 3:
            if coords[0] != coords[-1]:
                coords.append(coords[0])
            return {"type": "polygon", "geometry": json.dumps({"type": "Polygon", "coordinates": [coords]})}

        if len(coords) >= 1:
            lon, lat = coords[0]
            return {"type": "point", "geometry": json.dumps({"type": "Point", "coordinates": [lon, lat]})}

        return {"type": None, "geometry": None}
