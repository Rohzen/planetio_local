import json
import math
import requests
from typing import Dict, Any, List, Optional

BASE = "https://data-api.globalforestwatch.org"
VERIFY_SSL = True  # set False only for local debugging

class GFWError(Exception):
    pass

def get_access_token(email: str, password: str) -> str:
    headers = {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}
    data = {"username": email, "password": password}
    resp = requests.post(f"{BASE}/auth/token", headers=headers, data=data, timeout=30, verify=VERIFY_SSL)
    if not resp.ok:
        raise GFWError(f"Auth failed: {resp.status_code} {resp.text[:300]}")
    token = (resp.json().get("data") or {}).get("access_token")
    if not token:
        raise GFWError("Missing access_token in response")
    return token

def list_api_keys(access_token: str) -> List[dict]:
    resp = requests.get(f"{BASE}/auth/apikeys",
                        headers={"Authorization": f"Bearer {access_token}"},
                        timeout=30, verify=VERIFY_SSL)
    if not resp.ok:
        raise GFWError(f"List apikeys failed: {resp.status_code} {resp.text[:300]}")
    return resp.json().get("data", []) or []

def create_or_get_api_key(access_token: str, alias: str, email: str, organization: str, domains: Optional[List[str]] = None) -> str:
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    payload = {"alias": alias, "email": email, "organization": organization}
    if domains is not None:
        payload["domains"] = domains
    r = requests.post(f"{BASE}/auth/apikey", headers=headers, json=payload, timeout=30, verify=VERIFY_SSL)
    if r.status_code in (200, 201):
        return r.json()["data"][0]["api_key"]
    if r.status_code != 409:
        raise GFWError(f"Create apikey failed: {r.status_code} {r.text[:300]}")

    # 409 alias already exists: search in current keys
    for it in list_api_keys(access_token):
        if (it.get("alias","").lower() == alias.lower()):
            if not it.get("domains"):
                # create a new one with domains safety
                import time as _t
                payload["alias"] = f"{alias}-{int(_t.time())}"
                payload["domains"] = domains or ["localhost"]
                r2 = requests.post(f"{BASE}/auth/apikey", headers=headers, json=payload, timeout=30, verify=VERIFY_SSL)
                if not r2.ok:
                    raise GFWError(f"Create apikey (with domains) failed: {r2.status_code} {r2.text[:300]}")
                return r2.json()["data"][0]["api_key"]
            return it["api_key"]

    # alias not found → create a fresh one
    payload["domains"] = domains or ["localhost"]
    r3 = requests.post(f"{BASE}/auth/apikey", headers=headers, json=payload, timeout=30, verify=VERIFY_SSL)
    if not r3.ok:
        raise GFWError(f"Create apikey (fallback) failed: {r3.status_code} {r3.text[:300]}")
    return r3.json()["data"][0]["api_key"]

def _test_geometry() -> Dict[str, Any]:
    return square_bbox(lat=0.5, lon=0.5, half_km=5.0)

def validate_api_key(api_key: str) -> bool:
    try:
        _ = query_integrated_alerts(api_key, _test_geometry(), date_from="2025-01-01", limit=1)
        return True
    except Exception:
        return False

def square_bbox(lat: float, lon: float, half_km: float = 5.0) -> Dict[str, Any]:
    dlat = half_km / 111.0
    dlon = half_km / (111.0 * max(0.1, abs(math.cos(math.radians(lat)))))
    coords = [
        [lon - dlon, lat - dlat],
        [lon + dlon, lat - dlat],
        [lon + dlon, lat + dlat],
        [lon - dlon, lat + dlat],
        [lon - dlon, lat - dlat],
    ]
    return {"type": "Polygon", "coordinates": [coords]}

def query_integrated_alerts(api_key: str, geometry_geojson: dict, date_from="2025-01-01", limit=5):
    url = f"{BASE}/dataset/gfw_integrated_alerts/latest/query/json"
    sql = ("SELECT longitude, latitude, gfw_integrated_alerts__date, "
           "gfw_integrated_alerts__intensity, gfw_integrated_alerts__confidence "
           f"FROM results WHERE gfw_integrated_alerts__date >= '{date_from}' LIMIT {int(limit)}")
    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json",
        "Origin": "http://localhost",
    }
    resp = requests.post(url, headers=headers, json={"sql": sql, "geometry": geometry_geojson}, timeout=60, verify=VERIFY_SSL)
    if not resp.ok:
        raise GFWError(f"Query failed: {resp.status_code} {resp.text[:300]}")
    return resp.json().get("data", []) or []
