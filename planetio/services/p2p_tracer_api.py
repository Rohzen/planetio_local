# -*- coding: utf-8 -*-
import json
import math
import requests

from odoo import models, api, fields


class TracerAPI(models.AbstractModel):
    _name = "planetio.tracer.api"
    _description = "Planetio Tracer API Integration"

    # ------------------------- Config -------------------------
    def _cfg(self):
        icp = self.env["ir.config_parameter"].sudo()
        base_url = (icp.get_param("planetio.tracer_base_url", default="https://tracer-development.azure.startplanting.org") or "").rstrip("/")
        endpoint = icp.get_param("planetio.tracer_endpoint", default="/api/farm-data")
        api_key  = icp.get_param("planetio.tracer_api_key", default="")
        buffer_m = float(icp.get_param("planetio.tracer_buffer_meters", default="30") or 30)
        commodity_raw = icp.get_param("planetio.tracer_commodity", default="coffee")
        commodities = [c.strip() for c in commodity_raw.split(",") if c.strip()] or ["coffee"]
        return base_url, endpoint, api_key, buffer_m, commodities

    # ------------------------- Utils -------------------------
    @staticmethod
    def _meters_to_degrees(lat_deg, meters):
        lat_rad = math.radians(float(lat_deg))
        dlat = meters / 111_320.0
        dlon = meters / (111_320.0 * max(0.1, math.cos(lat_rad)))
        return dlat, dlon

    def _square_around_point(self, lat, lon, meters):
        dlat, dlon = self._meters_to_degrees(lat, meters)
        lat = float(lat); lon = float(lon)
        return [
            [lon - dlon, lat - dlat],
            [lon - dlon, lat + dlat],
            [lon + dlon, lat + dlat],
            [lon + dlon, lat - dlat],
            [lon - dlon, lat - dlat],
        ]

    # ------------------------- Feature builder -------------------------
    def _feature_from_row(self, r, idx, job, buffer_m, commodities):
        geom_json = r.get("geometry")
        if isinstance(geom_json, str):
            try:
                geom_json = json.loads(geom_json)
            except Exception:
                geom_json = None
        if not geom_json:
            return None, {"status": "error", "message": "missing geometry"}

        gtype = (geom_json.get("type") or "").lower()
        uid = f"job{job.id}-row{idx}"

        if gtype == "point":
            coords = geom_json.get("coordinates") or []
            if len(coords) < 2 or coords[0] is None or coords[1] is None:
                return None, {"status": "error", "message": "invalid point"}
            lon, lat = coords[:2]
            ring = self._square_around_point(lat, lon, buffer_m)
            polygon = {"type": "Polygon", "coordinates": [ring]}
            feature = {"type": "Feature", "properties": {"uid": uid, "commodity": commodities}, "geometry": polygon}
            return feature, None

        if gtype == "polygon":
            feature = {"type": "Feature", "properties": {"uid": uid, "commodity": commodities}, "geometry": geom_json}
            return feature, None

        return None, {"status": "error", "message": f"unsupported geometry: {gtype}"}

    # ------------------------- HTTP calls -------------------------
    def _post_farm_data(self, base_url, endpoint, api_key, feature):
        url = f"{base_url}{endpoint}"
        headers = {"Content-Type": "application/json", "x-api-key": api_key}
        payload = {"geoJSON": {"type": "FeatureCollection", "features": [feature]}}
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=60)
        except Exception as e:
            return {"status": "error", "message": f"network error: {e}", "properties": {}}

        if resp.status_code == 200:
            try:
                feat = (resp.json().get("features") or [{}])[0]
                return {"status": "ok", "message": "analyzed", "properties": feat.get("properties", {})}
            except Exception:
                return {"status": "ok", "message": "analyzed (no JSON)", "properties": {}}

        if resp.status_code == 409:
            uid = feature.get("properties", {}).get("uid")
            if not uid:
                return {"status": "error", "message": "conflict without uid", "properties": {}}
            try:
                g = requests.get(f"{url}?uid={uid}", headers={"x-api-key": api_key}, timeout=30)
                if g.status_code == 200:
                    feat = (g.json().get("features") or [{}])[0]
                    return {"status": "ok", "message": "retrieved", "properties": feat.get("properties", {})}
                return {"status": "error", "message": f"GET {g.status_code}", "properties": {}}
            except Exception as e:
                return {"status": "error", "message": f"GET error: {e}", "properties": {}}

        return {"status": "error", "message": f"POST {resp.status_code}: {resp.text[:200]}", "properties": {}}

    # ------------------------- Public API -------------------------
    @api.model
    def analyze_job(self, job):
        base_url, endpoint, api_key, buffer_m, commodities = self._cfg()

        # righe validate
        rows = None
        try:
            obj = json.loads(job.result_json) if isinstance(job.result_json, str) else job.result_json
            if isinstance(obj, dict) and "valid" in obj:
                rows = obj["valid"]
        except Exception:
            rows = None
        if rows is None:
            rows = self.env["excel.import.service"].validate_rows(job).get("valid", [])

        results = []
        for idx, r in enumerate(rows, start=1):
            feature, err = self._feature_from_row(r, idx, job, buffer_m, commodities)
            if err:
                results.append({"row": idx, "uid": None, "status": err["status"], "message": err["message"], "properties": {}})
                continue
            uid = feature["properties"]["uid"]
            resp = self._post_farm_data(base_url, endpoint, api_key, feature)
            props = resp.get("properties") or {}

            flags = []
            for k in ("deforestation_free", "protected_free"):
                v = props.get(k)
                if isinstance(v, str):
                    v = v.strip().lower() in ("1", "true", "yes", "y")
                if v is not None:
                    flags.append(bool(v))
            status = "pass" if (flags and all(flags)) else ("ok" if resp["status"] == "ok" else "fail")

            results.append({
                "row": idx,
                "uid": uid,
                "status": status,
                "message": resp.get("message", ""),
                "properties": props,
            })

        return {"base_url": base_url, "endpoint": endpoint, "results": results}

    @api.model
    def update_lines_from_results(self, declaration, results):
        """Aggiorna le righe della declaration in base agli uid e ai risultati API."""
        if not declaration:
            return 0
        Line = self.env["eudr.declaration.line"].sudo()
        updated = 0
        by_uid = {r.get("uid"): r for r in results if r.get("uid")}
        if not by_uid:
            return 0
        lines = Line.search([("declaration_id", "=", declaration.id), ("external_uid", "in", list(by_uid.keys()))])
        for line in lines:
            r = by_uid.get(line.external_uid) or {}
            vals = {
                "external_status": r.get("status"),
                "external_message": r.get("message"),
                "external_properties_json": json.dumps(r.get("properties") or {}, ensure_ascii=False),
            }
            line.write(vals)
            updated += 1
        return updated

    @api.model
    def analyze_job_and_update(self, job):
        """Comodo per il wizard: analizza e aggiorna subito le righe create dal job."""
        data = self.analyze_job(job)
        decl = getattr(job, "declaration_id", False)
        if decl:
            self.update_lines_from_results(decl, data.get("results", []))
        return data
