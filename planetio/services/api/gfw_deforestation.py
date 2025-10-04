# -*- coding: utf-8 -*-
import json
import math
from datetime import date, datetime, timedelta

import requests

from odoo import models, _, tools
from odoo.exceptions import UserError


class DeforestationProviderGFW(models.AbstractModel):
    _name = 'deforestation.provider.gfw'
    _inherit = 'deforestation.provider.base'
    _description = 'Deforestation Provider - GFW'

    # --------- Config / prerequisites ---------
    def _get_api_key(self):
        icp = self.env['ir.config_parameter'].sudo()
        key = (icp.get_param('planetio.gfw_api_key') or '').strip()
        return key or None

    def check_prerequisites(self):
        if not self._get_api_key():
            raise UserError(_("GFW API Key mancante. Imposta 'GFW API Key' nelle Impostazioni."))

    # --------- Geometry helpers ---------
    def _geometry_center(self, geom):
        if not geom or not isinstance(geom, dict):
            return None, None
        gtype = geom.get('type')
        if gtype == 'Point':
            coords = geom.get('coordinates') or []
            if len(coords) >= 2:
                return float(coords[0]), float(coords[1])
            return None, None
        if gtype == 'Polygon':
            ring = (geom.get('coordinates') or [[]])[0] or []
            if not ring:
                return None, None
            lons = [p[0] for p in ring if isinstance(p, (list, tuple)) and len(p) >= 2]
            lats = [p[1] for p in ring if isinstance(p, (list, tuple)) and len(p) >= 2]
            if not lons or not lats:
                return None, None
            return (min(lons) + max(lons)) / 2.0, (min(lats) + max(lats)) / 2.0
        return None, None

    def _approx_polygon_area_ha(self, geom):
        if not geom or geom.get('type') != 'Polygon':
            return 0.0
        ring = (geom.get('coordinates') or [[]])[0] or []
        if not ring:
            return 0.0
        lons = [p[0] for p in ring if isinstance(p, (list, tuple)) and len(p) >= 2]
        lats = [p[1] for p in ring if isinstance(p, (list, tuple)) and len(p) >= 2]
        if not lons or not lats:
            return 0.0
        lon_min, lon_max = min(lons), max(lons)
        lat_min, lat_max = min(lats), max(lats)
        lat_c = (lat_min + lat_max) / 2.0
        dlat_per_m = 1.0 / 111000.0
        dlon_per_m = 1.0 / (111000.0 * max(0.1, abs(math.cos(math.radians(lat_c)))))
        width_m = max(0.0, (lon_max - lon_min) / dlon_per_m)
        height_m = max(0.0, (lat_max - lat_min) / dlat_per_m)
        return (width_m * height_m) / 10000.0

    def _square_from_center(self, lon, lat, area_ha):
        if lon is None or lat is None:
            return None
        area_m2 = max(float(area_ha), 0.0) * 10000.0
        if area_m2 == 0.0:
            return None
        side_m = math.sqrt(area_m2)
        half_side_m = side_m / 2.0
        dlat = half_side_m / 111000.0
        dlon = half_side_m / (111000.0 * max(0.1, abs(math.cos(math.radians(lat)))))
        return {
            'type': 'Polygon',
            'coordinates': [[
                [lon - dlon, lat - dlat],
                [lon + dlon, lat - dlat],
                [lon + dlon, lat + dlat],
                [lon - dlon, lat + dlat],
                [lon - dlon, lat - dlat],
            ]],
        }

    def _ensure_min_area_geometry(self, geom, min_area_ha):
        if not isinstance(geom, dict):
            return geom, 'original'
        min_area_ha = float(min_area_ha or 0.0)
        if min_area_ha <= 0.0:
            return geom, geom.get('type') or 'original'

        gtype = geom.get('type')
        if gtype == 'Point':
            lon, lat = self._geometry_center(geom)
            expanded = self._square_from_center(lon, lat, min_area_ha)
            return (expanded or geom), 'point_expanded'

        if gtype == 'Polygon':
            area_ha = self._approx_polygon_area_ha(geom)
            if area_ha >= min_area_ha:
                return geom, 'polygon'
            lon, lat = self._geometry_center(geom)
            expanded = self._square_from_center(lon, lat, min_area_ha)
            return (expanded or geom), 'polygon_expanded'

        return geom, gtype or 'original'

    # --------- HTTP helpers ---------
    def _prepare_headers(self, origin, api_key):
        return {
            'x-api-key': api_key,
            'Content-Type': 'application/json',
            'Origin': origin,
        }

    def _post_query(self, url, headers, sql, geometry):
        payload = {'sql': sql}
        if geometry:
            payload['geometry'] = geometry
        return requests.post(url, headers=headers, json=payload, timeout=90)

    def _safe_json(self, response):
        try:
            return response.json()
        except Exception:
            return {'data': []}

    # --------- Data extraction helpers ---------
    def _extract_number(self, row, keys):
        if not isinstance(row, dict):
            return None
        for key in keys:
            if key in row and row[key] not in (None, ''):
                try:
                    return float(row[key])
                except Exception:
                    try:
                        return float(str(row[key]).replace(',', '.'))
                    except Exception:
                        continue
        return None

    def _extract_text(self, row, keys):
        if not isinstance(row, dict):
            return None
        for key in keys:
            val = row.get(key)
            if val not in (None, ''):
                return tools.ustr(val)
        return None

    def _parse_iso_date(self, value):
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value)[:10]).date()
        except Exception:
            return None

    # --------- Dataset querying ---------
    def _prepare_dataset_base(self, dataset_id):
        return f'https://data-api.globalforestwatch.org/dataset/{dataset_id}'

    def _gfw_execute_sql(self, headers, geometry, sql_template, date_from, allow_short=True):
        base_url = self._prepare_dataset_base('gfw_integrated_alerts')
        sql_long = sql_template.replace('{date_from}', date_from)
        latest_url = f'{base_url}/latest/query/json'
        version_url = f'{base_url}/v20250909/query/json'

        try:
            response = self._post_query(latest_url, headers, sql_long, geometry)
        except requests.exceptions.RequestException as ex:
            raise UserError(_("Connessione a GFW non riuscita: %s") % tools.ustr(ex))

        if response.status_code < 500:
            if response.status_code >= 400:
                snippet = (response.text or '')[:300]
                raise UserError(_("Provider gfw: Richiesta rifiutata da GFW: %s") % tools.ustr(snippet or response.status_code))
            return self._safe_json(response), {
                'endpoint': 'latest',
                'date_from': date_from,
                'sql': sql_long,
                'status_code': response.status_code,
            }

        if allow_short:
            short_from = (date.today() - timedelta(days=90)).isoformat()
            sql_short = sql_template.replace('{date_from}', short_from)
            try:
                short_resp = self._post_query(latest_url, headers, sql_short, geometry)
            except requests.exceptions.RequestException as ex:
                raise UserError(_("Connessione a GFW non riuscita: %s") % tools.ustr(ex))
            if short_resp.status_code < 500:
                if short_resp.status_code >= 400:
                    snippet = (short_resp.text or '')[:300]
                    raise UserError(_("Provider gfw: Richiesta rifiutata da GFW: %s") % tools.ustr(snippet or short_resp.status_code))
                return self._safe_json(short_resp), {
                    'endpoint': 'latest',
                    'date_from': short_from,
                    'sql': sql_short,
                    'status_code': short_resp.status_code,
                    'fallback': '90d',
                }

        try:
            version_resp = self._post_query(version_url, headers, sql_long, geometry)
        except requests.exceptions.RequestException as ex:
            raise UserError(_("Connessione a GFW non riuscita: %s") % tools.ustr(ex))

        if version_resp.status_code >= 400:
            snippet = (version_resp.text or '')[:300]
            raise UserError(_("Provider gfw: Richiesta rifiutata da GFW: %s") % tools.ustr(snippet or version_resp.status_code))

        return self._safe_json(version_resp), {
            'endpoint': 'v20250909',
            'date_from': date_from,
            'sql': sql_long,
            'status_code': version_resp.status_code,
            'fallback': 'version',
        }

    def _gfw_execute_sql_on_dataset(self, headers, geometry, dataset_id, sql_template, date_from):
        base_url = self._prepare_dataset_base(dataset_id)
        latest_url = f'{base_url}/latest/query/json'
        sql = sql_template.replace('{date_from}', date_from)
        try:
            resp = self._post_query(latest_url, headers, sql, geometry)
        except requests.exceptions.RequestException as ex:
            raise UserError(_("Connessione a GFW non riuscita: %s") % tools.ustr(ex))
        if resp.status_code >= 400:
            snippet = (resp.text or '')[:300]
            raise UserError(_("Provider gfw: Richiesta rifiutata da GFW: %s") % tools.ustr(snippet or resp.status_code))
        return self._safe_json(resp), {
            'endpoint': 'latest',
            'date_from': date_from,
            'sql': sql,
            'status_code': resp.status_code,
            'dataset': dataset_id,
        }

    # --------- Safe runners ---------
    def _run_integrated_all_best_effort(self, headers, geom_to_use, start_date, debug_errors,
                                        allow_short_for_agg=True, count_field=None, area_field='area__ha'):
        df = 'gfw_integrated_alerts__date'
        count_expr = f"SUM({count_field})" if count_field else "COUNT(*)"
        area_expr = f"SUM({area_field})" if area_field else "SUM(area__ha)"
        agg_sql = (
            f"SELECT {count_expr} AS alert_count, {area_expr} AS area_ha_total, "
            f"MIN({df}) AS first_alert_date, MAX({df}) AS last_alert_date "
            f"FROM results WHERE {df} >= '{{date_from}}'"
        )
        ser_sql = (
            f"SELECT {df} AS alert_date, {count_expr} AS alert_count, {area_expr} AS area_ha "
            f"FROM results WHERE {df} >= '{{date_from}}' "
            f"GROUP BY {df} ORDER BY alert_date DESC LIMIT 365"
        )
        brk_sql = (
            f"SELECT {df} AS alert_date, {count_expr} AS alert_count, {area_expr} AS area_ha, "
            f"MAX(gfw_integrated_alerts__confidence) AS confidence "
            f"FROM results WHERE {df} >= '{{date_from}}' "
            f"GROUP BY {df} ORDER BY alert_date DESC LIMIT 200"
        )
        agg_data, agg_info = self._gfw_execute_sql(headers, geom_to_use, agg_sql, start_date, allow_short=allow_short_for_agg)
        ser_data = {'data': []}
        ser_info = {'endpoint': None, 'date_from': start_date}
        brk_data = {'data': []}
        brk_info = {'endpoint': None, 'date_from': start_date}
        try:
            ser_data, ser_info = self._gfw_execute_sql(headers, geom_to_use, ser_sql, agg_info['date_from'], allow_short=False)
        except Exception as ex:
            debug_errors.append(f"series_best_effort_error: {tools.ustr(ex)}")
        try:
            brk_data, brk_info = self._gfw_execute_sql(headers, geom_to_use, brk_sql, agg_info['date_from'], allow_short=False)
        except Exception as ex:
            debug_errors.append(f"breakdown_best_effort_error: {tools.ustr(ex)}")
        return agg_data, agg_info, ser_data, ser_info, brk_data, brk_info

    def _date_field_for_dataset(self, dataset_id):
        return {
            'gfw_integrated_alerts': 'gfw_integrated_alerts__date',
            'umd_glad_sentinel2_alerts': 'umd_glad_sentinel2_alerts__date',
            'wur_radd_alerts': 'wur_radd_alerts__date',
            'umd_glad_landsat_alerts': 'umd_glad_landsat_alerts__date',
        }.get(dataset_id, 'gfw_integrated_alerts__date')

    def _run_alert_details_best_effort(self, headers, geom_to_use, start_date, dataset_id, debug_errors):
        df = self._date_field_for_dataset(dataset_id)
        select_fields = [
            f"{df} AS alert_date",
            "cartodb_id",
            "alert__id",
            "alert_id",
            "glad_id",
            "gladid",
            "area__ha",
            "MAX(gfw_integrated_alerts__confidence) AS confidence",
            "ST_Y(ST_Centroid(the_geom)) AS latitude",
            "ST_X(ST_Centroid(the_geom)) AS longitude",
        ]
        select_clause = ", ".join(select_fields)
        sql = (
            f"SELECT {select_clause} "
            f"FROM results WHERE {df} >= '{{date_from}}' "
            f"ORDER BY {df} DESC LIMIT 200"
        )
        try:
            return self._gfw_execute_sql_on_dataset(headers, geom_to_use, dataset_id, sql, start_date)
        except Exception as ex:
            debug_errors.append(f"details_best_effort_error[{dataset_id}]: {tools.ustr(ex)}")
            return {'data': []}, {'endpoint': None, 'date_from': start_date, 'dataset': dataset_id}

    # --------- Geometry extraction ---------
    def _extract_geometry(self, line):
        geom = None
        if hasattr(line, '_line_geometry'):
            try:
                geom = line._line_geometry()
            except Exception:
                geom = None
        if not geom:
            raw = getattr(line, 'geojson', None) or getattr(line, 'geometry_geojson', None)
            if raw:
                try:
                    geom = json.loads(raw) if isinstance(raw, str) else raw
                except Exception:
                    geom = None
        return geom if isinstance(geom, dict) and geom.get('type') else None

    # --------- Date window ---------
    def _compute_date_from(self):
        ICP = self.env['ir.config_parameter'].sudo()
        raw_years = ICP.get_param('planetio.gfw_alert_years')
        try:
            years_back = int(raw_years) if raw_years else 0
        except Exception:
            years_back = 0
        if years_back <= 0:
            raw_days = ICP.get_param('planetio.gfw_days_back')
            try:
                days_val = int(raw_days) if raw_days else 365
            except Exception:
                days_val = 365
            years_back = max(1, int(math.ceil(days_val / 365.0)))
        years_back = max(1, min(5, years_back))
        days_back = years_back * 365
        return (date.today() - timedelta(days=days_back)).isoformat()

    # --------- Main ---------
    def analyze_line(self, line):
        self.check_prerequisites()
        api_key = self._get_api_key()
        ICP = self.env['ir.config_parameter'].sudo()
        origin = (ICP.get_param('planetio.gfw_api_origin') or 'http://localhost').strip()

        def _get_float(key, default):
            try:
                return float(ICP.get_param(key) or default)
            except Exception:
                return default

        min_area_ha_req = _get_float('planetio.gfw_min_area_ha', 4.0)
        collapse_when_missing_geo = (ICP.get_param('planetio.gfw_collapse_when_missing_geo') or 'True').strip().lower() in (
            '1', 'true', 'y', 'yes')
        max_detail_rows = int(ICP.get_param('planetio.gfw_max_detail_rows') or 80)

        geom = self._extract_geometry(line)
        if not geom:
            raise UserError(_("Manca geometria (GeoJSON o lat/lon) sulla riga %s") %
                            (getattr(line, 'display_name', None) or line.id))

        final_geom_used, geometry_mode = self._ensure_min_area_geometry(geom, min_area_ha_req)

        date_from = self._compute_date_from()
        headers = self._prepare_headers(origin, api_key)
        debug_errors = []

        agg_data, agg_info, ser_data, ser_info, brk_data, brk_info = self._run_integrated_all_best_effort(
            headers, final_geom_used, date_from, debug_errors, allow_short_for_agg=True)

        row = (agg_data.get('data') or [{}])[0]
        alert_count = self._extract_number(row, ['alert_count', 'cnt', 'count']) or 0.0
        area_total = self._extract_number(row, ['area_ha_total', 'area_ha', 'area']) or 0.0
        first_alert = self._extract_text(row, ['first_alert_date'])
        last_alert = self._extract_text(row, ['last_alert_date'])

        def _series_to_entries(ser_obj):
            out = []
            for r in ser_obj.get('data') or []:
                d = self._extract_text(r, ['alert_date', 'gfw_integrated_alerts__date', 'date'])
                if not d:
                    continue
                out.append({
                    'date': d,
                    'alert_count': self._extract_number(r, ['alert_count', 'count', 'cnt']) or 0.0,
                    'area_ha': self._extract_number(r, ['area_ha', 'area', 'area_ha_total']) or 0.0,
                })
            return out

        series_entries = _series_to_entries(ser_data)
        used_dataset = 'gfw_integrated_alerts'

        details_data = {'data': []}
        details_info = {'endpoint': None, 'date_from': agg_info.get('date_from') or date_from, 'dataset': used_dataset}
        try:
            details_data, details_info = self._run_alert_details_best_effort(
                headers, final_geom_used, agg_info.get('date_from') or date_from, used_dataset, debug_errors,
            )
        except Exception as ex:
            debug_errors.append(f"details_error[{used_dataset}]: {tools.ustr(ex)}")
            details_data = {'data': []}
            details_info = {'endpoint': None, 'date_from': agg_info.get('date_from') or date_from, 'dataset': used_dataset}

        center_lon, center_lat = self._geometry_center(final_geom_used)
        analysis_area_ha = self._approx_polygon_area_ha(final_geom_used) if final_geom_used and final_geom_used.get('type') == 'Polygon' else 0.0

        detail_entries = []
        detail_date_field = self._date_field_for_dataset(used_dataset)
        for rowD in (details_data.get('data') or []):
            date_token = None
            if isinstance(rowD, dict):
                date_token = self._extract_text(rowD, ['alert_date', detail_date_field, 'date'])
            if not date_token:
                date_token = self._extract_text(rowD, ['gfw_integrated_alerts__date'])
            if not date_token:
                continue

            lat = self._extract_number(rowD, ['latitude', 'lat', 'alert_lat', 'alert__lat', 'y'])
            lon = self._extract_number(rowD, ['longitude', 'lon', 'lng', 'alert_lon', 'alert__lon', 'x'])
            if lat is None or lon is None:
                lat, lon = center_lat, center_lon

            entry = {
                'date': date_token,
                'alert_id': self._extract_text(rowD, ['alert_id', 'alert__id', 'cartodb_id', 'id']),
                'alert_count': self._extract_number(rowD, ['alert_count', 'count', 'cnt']) or 1.0,
                'area_ha': self._extract_number(rowD, ['area_ha', 'area', 'area__ha', 'area_ha_total']) or 0.0,
                'confidence': self._extract_text(rowD, [
                    'confidence',
                    'gfw_integrated_alerts__confidence',
                    'umd_glad_sentinel2_alerts__confidence',
                    'umd_glad_landsat_alerts__confidence',
                    'wur_radd_alerts__confidence',
                ]),
                'latitude': lat,
                'longitude': lon,
                'description': used_dataset,
                'analysis_area_ha': analysis_area_ha,
                'provider': 'gfw',
            }
            detail_entries.append(entry)

        def _all_missing_geo(entries):
            if not entries:
                return True
            for e in entries:
                if (e.get('latitude') not in (None, 0.0) or e.get('longitude') not in (None, 0.0)) or (e.get('area_ha') and e.get('area_ha') > 0):
                    return False
            return True

        if (not detail_entries) or (collapse_when_missing_geo and _all_missing_geo(detail_entries)) or (len(detail_entries) > max_detail_rows):
            period_id = "period:%s→%s" % ((agg_info.get('date_from') or date_from), (last_alert or date.today().isoformat()))
            single = {
                'date': last_alert or (agg_info.get('date_from') or date_from),
                'alert_id': period_id,
                'alert_count': int(round(alert_count)) if alert_count else 0,
                'area_ha': 0.0,
                'confidence': self._extract_text((brk_data.get('data') or [{}])[0], ['confidence']) or 'n/a',
                'latitude': center_lat,
                'longitude': center_lon,
                'description': used_dataset,
                'analysis_area_ha': analysis_area_ha,
                'provider': 'gfw',
            }
            breakdown_entries = [single]
        else:
            breakdown_entries = detail_entries

        def _parse_date_safe(token):
            try:
                return self._parse_iso_date(token)
            except Exception:
                return None

        def _sum_recent(days):
            cutoff = date.today() - timedelta(days=days)
            total_count = 0.0
            total_area = 0.0
            for e in series_entries:
                d = _parse_date_safe(e.get('date'))
                if d and d >= cutoff:
                    total_count += e.get('alert_count') or 0.0
                    total_area += e.get('area_ha') or 0.0
            return total_count, total_area

        recent_30_count, recent_30_area = _sum_recent(30)
        recent_90_count, recent_90_area = _sum_recent(90)

        metrics = {
            'alert_count': int(round(alert_count)),
            'area_ha_total': float(area_total),
            'first_alert_date': first_alert,
            'last_alert_date': last_alert,
            'alert_count_30d': int(round(recent_30_count)),
            'area_ha_30d': float(recent_30_area),
            'alert_count_90d': int(round(recent_90_count)),
            'area_ha_90d': float(recent_90_area),
        }

        msg_parts = []
        if metrics['alert_count']:
            msg_parts.append(_("GFW Data API: %(n)s allerta/e rilevate dal %(d)s") % {
                'n': metrics['alert_count'], 'd': (agg_info.get('date_from') or date_from)
            })
        else:
            msg_parts.append(_("GFW Data API: nessuna allerta rilevata dal %(d)s") % {
                'd': (agg_info.get('date_from') or date_from)
            })
        if metrics['area_ha_total']:
            msg_parts.append(_("Area interessata: %(area).2f ha") % {'area': metrics['area_ha_total']})
        if metrics['last_alert_date']:
            msg_parts.append(_("Ultima allerta: %s") % metrics['last_alert_date'])
        message = "; ".join(msg_parts)

        meta = {
            'provider': 'gfw',
            'date_from': agg_info.get('date_from') or date_from,
            'dataset_endpoint': agg_info.get('endpoint'),
            'geometry_mode': geometry_mode,
            'used_dataset': used_dataset,
            'field_variant': {'count': 'COUNT(*)', 'area': 'area__ha'},
            'queries': {
                'aggregate': agg_info,
                'time_series': ser_info,
                'breakdown': brk_info,
                'details': details_info,
            },
            'original_geom': geom,
            'final_geom_used': final_geom_used,
            'analysis_area_ha': analysis_area_ha,
            'analysis_center': {'lon': center_lon, 'lat': center_lat},
            'debug': {
                'errors': debug_errors,
            },
        }

        details = {
            'metrics': metrics,
            'alerts': breakdown_entries,
            'time_series': series_entries,
            'responses': {
                'aggregate': agg_data,
                'time_series': ser_data,
                'breakdown': brk_data,
                'details': details_data,
            },
        }

        return {
            'message': message,
            'alerts': breakdown_entries,
            'metrics': metrics,
            'meta': meta,
            'details': details,
        }
