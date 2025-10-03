# -*- coding: utf-8 -*-
import math
import requests
from datetime import date, datetime, timedelta
from odoo import models, _, tools
from odoo.exceptions import UserError
import json


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

    # --------- Geo helpers ---------
    def _expand_point_to_bbox(self, geom):
        """Se la geom è un Point, espandi a un piccolo bbox (coerente col fallback)."""
        if not isinstance(geom, dict) or geom.get('type') != 'Point':
            return None
        coords = geom.get('coordinates') or []
        if len(coords) < 2:
            return None
        lon, lat = coords[0], coords[1]
        try:
            dlat = 0.2 / 111.0
            dlon = 0.2 / (111.0 * max(0.1, abs(math.cos(math.radians(lat)))))
        except Exception:
            return None
        return {
            'type': 'Polygon',
            'coordinates': [[
                [lon - dlon, lat - dlat],
                [lon + dlon, lat - dlat],
                [lon + dlon, lat + dlat],
                [lon - dlon, lat + dlat],
                [lon - dlon, lat - dlat],
            ]]
        }

    def _maybe_buffer_tiny_polygon(self, geom, min_m=60.0, min_area_ha=None, area_policy='buffer'):
        """
        Se geom è un Polygon troppo piccolo:
          - modalità 'buffer'  : espandi a lato >= min_m e/o area >= min_area_ha
          - modalità 'strict'  : NON espandere; segnala che la geometria è sotto soglia
        Ritorna: (geom_out, changed_bool, info_dict)
        Se strict & sotto soglia: changed=False e info['too_small_strict']=True
        """
        if not isinstance(geom, dict) or geom.get('type') != 'Polygon':
            return geom, False, None
        try:
            ring = geom['coordinates'][0]
            lons = [p[0] for p in ring]
            lats = [p[1] for p in ring]
            lon_min, lon_max = min(lons), max(lons)
            lat_min, lat_max = min(lats), max(lats)
            lat_c = (lat_min + lat_max) / 2.0

            # gradi per metro
            dlat_per_m = 1.0 / 111000.0
            dlon_per_m = 1.0 / (111000.0 * max(0.1, abs(math.cos(math.radians(lat_c)))))

            width_m = max(0.0, (lon_max - lon_min) / dlon_per_m)
            height_m = max(0.0, (lat_max - lat_min) / dlat_per_m)
            area_m2 = width_m * height_m

            needs_by_side = (width_m < min_m) or (height_m < min_m)
            needs_by_area = False
            target_side_m = None
            if min_area_ha is not None and float(min_area_ha) > 0:
                min_area_m2 = float(min_area_ha) * 10000.0
                if area_m2 < min_area_m2:
                    needs_by_area = True
                    target_side_m = math.sqrt(min_area_m2)

            # STRICT: non espandere, segnala la condizione
            if area_policy == 'strict' and (needs_by_side or needs_by_area):
                return geom, False, {
                    'width_m': width_m,
                    'height_m': height_m,
                    'area_m2': area_m2,
                    'min_m': min_m,
                    'min_area_ha': min_area_ha,
                    'action': 'strict_reject',
                    'too_small_strict': True,
                }

            # BUFFER: se non serve nulla, mantieni
            if not (needs_by_side or needs_by_area):
                return geom, False, {
                    'width_m': width_m,
                    'height_m': height_m,
                    'area_m2': area_m2,
                    'min_m': min_m,
                    'min_area_ha': min_area_ha,
                    'action': 'keep'
                }

            # BUFFER: costruisci un bbox quadrato centrato che rispetti entrambe le soglie
            cx = (lon_min + lon_max) / 2.0
            cy = (lat_min + lat_max) / 2.0

            side_from_min_m = max(min_m, width_m, height_m)
            side_from_area = target_side_m or 0.0
            final_side_m = max(side_from_min_m, side_from_area)
            half_side_m = final_side_m / 2.0

            dlon = half_side_m * dlon_per_m
            dlat = half_side_m * dlat_per_m

            expanded = {
                'type': 'Polygon',
                'coordinates': [[
                    [cx - dlon, cy - dlat],
                    [cx + dlon, cy - dlat],
                    [cx + dlon, cy + dlat],
                    [cx - dlon, cy + dlat],
                    [cx - dlon, cy - dlat],
                ]]
            }
            return expanded, True, {
                'width_m': width_m,
                'height_m': height_m,
                'area_m2': area_m2,
                'min_m': min_m,
                'min_area_ha': min_area_ha,
                'final_side_m': final_side_m,
                'action': 'expanded'
            }
        except Exception:
            return geom, False, {'error': 'buffer_failed', 'min_area_ha': min_area_ha, 'area_policy': area_policy}

    def _bbox_hint(self, geom):
        """Hint bbox {minx,miny,maxx,maxy} per la geom (Polygon/Point), utile per debug."""
        try:
            if not geom or not isinstance(geom, dict):
                return None
            gtype = geom.get('type')
            if gtype == 'Polygon':
                ring = geom.get('coordinates', [[]])[0] or []
                lons = [p[0] for p in ring if isinstance(p, (list, tuple)) and len(p) >= 2]
                lats = [p[1] for p in ring if isinstance(p, (list, tuple)) and len(p) >= 2]
                if not lons or not lats:
                    return None
                return {'minx': min(lons), 'miny': min(lats), 'maxx': max(lons), 'maxy': max(lats)}
            if gtype == 'Point':
                lon, lat = geom.get('coordinates', [None, None])[:2]
                if lon is None or lat is None:
                    return None
                eps = 1e-6
                return {'minx': lon - eps, 'miny': lat - eps, 'maxx': lon + eps, 'maxy': lat + eps}
            return None
        except Exception:
            return None

    # --------- Low-level HTTP/Data API helpers ---------
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

    # --------- Generic extractors ---------
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

        attempts = []
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

        attempts.append({'endpoint': 'latest', 'status_code': response.status_code, 'date_from': date_from})

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
            attempts.append({'endpoint': 'latest', 'status_code': short_resp.status_code, 'date_from': short_from, 'fallback': '90d'})

        try:
            version_resp = self._post_query(version_url, headers, sql_long, geometry)
        except requests.exceptions.RequestException as ex:
            raise UserError(_("Connessione a GFW non riuscita: %s") % tools.ustr(ex))

        if version_resp.status_code >= 400:
            snippet = (version_resp.text or '')[:300]
            raise UserError(_("Provider gfw: Richiesta rifiutata da GFW: %s") % tools.ustr(snippet or version_resp.status_code))

        if version_resp.status_code >= 500:
            details = "; ".join(f"{item['endpoint']} ({item.get('fallback', 'full')}): {item['status_code']}" for item in attempts)
            raise UserError(_("Provider gfw: nessuna risposta valida dal Data API (%s)") % details)

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
            'dataset': dataset_id
        }

    # --------- Diagnostics ---------
    def _diag_nearby_sources(self, headers, center_lon, center_lat, radius_m, date_from):
        dlat_per_m = 1.0 / 111000.0
        dlon_per_m = 1.0 / (111000.0 * max(0.1, abs(math.cos(math.radians(center_lat)))))
        dlat = radius_m * dlat_per_m
        dlon = radius_m * dlon_per_m
        diag_geom = {
            'type': 'Polygon',
            'coordinates': [[
                [center_lon - dlon, center_lat - dlat],
                [center_lon + dlon, center_lat - dlat],
                [center_lon + dlon, center_lat + dlat],
                [center_lon - dlon, center_lat + dlat],
                [center_lon - dlon, center_lat - dlat],
            ]]
        }

        datasets = {
            'gfw_integrated_alerts': ('Integrated', 'gfw_integrated_alerts__date'),
            'umd_glad_landsat_alerts': ('GLAD_L', 'umd_glad_landsat_alerts__date'),
            'umd_glad_sentinel2_alerts': ('GLAD_S2', 'umd_glad_sentinel2_alerts__date'),
            'wur_radd_alerts': ('RADD', 'wur_radd_alerts__date'),
        }

        results = {}
        for ds_id, (label, df) in datasets.items():
            sql = (
                f"SELECT COUNT(*) AS alert_count, "
                f"SUM(area__ha) AS area_ha_total, "
                f"MIN({df}) AS first_alert_date, "
                f"MAX({df}) AS last_alert_date "
                f"FROM results WHERE {df} >= '{{date_from}}'"
            )
            data, info = self._gfw_execute_sql_on_dataset(headers, diag_geom, ds_id, sql, date_from)
            row = (data.get('data') or [{}])[0]
            results[label] = {
                'count': int(self._extract_number(row, ['alert_count', 'count', 'cnt']) or 0),
                'area_ha': float(self._extract_number(row, ['area_ha_total', 'area', 'area_ha']) or 0.0),
                'first': self._extract_text(row, ['first_alert_date', 'first', 'min']),
                'last': self._extract_text(row, ['last_alert_date', 'last', 'max']),
                'query': info,
            }
        return {'radius_m': radius_m, 'geometry': diag_geom, 'by_dataset': results}

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

    def _date_field_for_dataset(self, dataset_id):
        return {
            'gfw_integrated_alerts':     'gfw_integrated_alerts__date',
            'umd_glad_sentinel2_alerts': 'umd_glad_sentinel2_alerts__date',
            'wur_radd_alerts':           'wur_radd_alerts__date',
            'umd_glad_landsat_alerts':   'umd_glad_landsat_alerts__date',
        }.get(dataset_id, 'gfw_integrated_alerts__date')

    # --------- Safe runners ---------
    def _run_aggregate_on_dataset(self, headers, geom_to_use, start_date, dataset_id):
        df = self._date_field_for_dataset(dataset_id)
        agg_sql = (
            f"SELECT COUNT(*) AS alert_count, SUM(area__ha) AS area_ha_total, "
            f"MIN({df}) AS first_alert_date, MAX({df}) AS last_alert_date "
            f"FROM results WHERE {df} >= '{{date_from}}'"
        )
        agg, agg_info = self._gfw_execute_sql_on_dataset(headers, geom_to_use, dataset_id, agg_sql, start_date)
        return agg, agg_info

    def _run_series_breakdown_best_effort(self, headers, geom_to_use, start_date, dataset_id, debug_errors):
        df = self._date_field_for_dataset(dataset_id)
        ser_sql = (
            f"SELECT {df} AS alert_date, COUNT(*) AS alert_count, SUM(area__ha) AS area_ha "
            f"FROM results WHERE {df} >= '{{date_from}}' "
            f"GROUP BY {df} ORDER BY alert_date DESC LIMIT 365"
        )
        brk_sql = (
            f"SELECT {df} AS alert_date, COUNT(*) AS alert_count, SUM(area__ha) AS area_ha "
            f"FROM results WHERE {df} >= '{{date_from}}' "
            f"GROUP BY {df} ORDER BY alert_date DESC LIMIT 200"
        )
        ser = {'data': []}; ser_info = {'endpoint': None, 'date_from': start_date, 'dataset': dataset_id}
        brk = {'data': []}; brk_info = {'endpoint': None, 'date_from': start_date, 'dataset': dataset_id}
        try:
            ser, ser_info = self._gfw_execute_sql_on_dataset(headers, geom_to_use, dataset_id, ser_sql, start_date)
        except Exception as ex:
            debug_errors.append(f"series_best_effort_error[{dataset_id}]: {tools.ustr(ex)}")
        try:
            brk, brk_info = self._gfw_execute_sql_on_dataset(headers, geom_to_use, dataset_id, brk_sql, start_date)
        except Exception as ex:
            debug_errors.append(f"breakdown_best_effort_error[{dataset_id}]: {tools.ustr(ex)}")
        return ser, ser_info, brk, brk_info

    def _detail_select_variants(self, dataset_id, date_field):
        base_coords = [
            "ST_Y(ST_Centroid(the_geom)) AS latitude",
            "ST_X(ST_Centroid(the_geom)) AS longitude",
        ]

        dataset_conf = {
            'gfw_integrated_alerts': ['gfw_integrated_alerts__confidence'],
            'umd_glad_sentinel2_alerts': ['umd_glad_sentinel2_alerts__confidence'],
            'umd_glad_landsat_alerts': ['umd_glad_landsat_alerts__confidence'],
            'wur_radd_alerts': ['wur_radd_alerts__confidence'],
        }.get(dataset_id, [])

        select_variants = []

        detail_fields = [
            f"{date_field} AS alert_date",
            "cartodb_id",
            "alert__id",
            "alert_id",
            "glad_id",
            "gladid",
            "area__ha",
        ]
        detail_fields.extend(dataset_conf)
        detail_fields.extend(base_coords)
        select_variants.append(detail_fields)

        minimal_fields = [
            f"{date_field} AS alert_date",
            "cartodb_id",
            "area__ha",
        ]
        minimal_fields.extend(dataset_conf)
        minimal_fields.extend(base_coords)
        select_variants.append(minimal_fields)

        return select_variants

    def _run_alert_details_best_effort(self, headers, geom_to_use, start_date, dataset_id, debug_errors):
        df = self._date_field_for_dataset(dataset_id)
        variants = self._detail_select_variants(dataset_id, df)
        last_exc = None
        for fields in variants:
            select_clause = ", ".join(fields)
            sql = (
                f"SELECT {select_clause} "
                f"FROM results WHERE {df} >= '{{date_from}}' "
                f"ORDER BY {df} DESC LIMIT 200"
            )
            try:
                return self._gfw_execute_sql_on_dataset(headers, geom_to_use, dataset_id, sql, start_date)
            except Exception as ex:
                last_exc = ex
                debug_errors.append(f"details_best_effort_error[{dataset_id}]: {tools.ustr(ex)}")
        if last_exc:
            raise last_exc
        return {'data': []}, {'endpoint': None, 'date_from': start_date, 'dataset': dataset_id}

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
        ser_data = {'data': []}; ser_info = {'endpoint': None, 'date_from': start_date}
        brk_data = {'data': []}; brk_info = {'endpoint': None, 'date_from': start_date}
        try:
            ser_data, ser_info = self._gfw_execute_sql(headers, geom_to_use, ser_sql, agg_info['date_from'], allow_short=False)
        except Exception as ex:
            debug_errors.append(f"series_best_effort_error[integrated]: {tools.ustr(ex)}")
        try:
            brk_data, brk_info = self._gfw_execute_sql(headers, geom_to_use, brk_sql, agg_info['date_from'], allow_short=False)
        except Exception as ex:
            debug_errors.append(f"breakdown_best_effort_error[integrated]: {tools.ustr(ex)}")
        return agg_data, agg_info, ser_data, ser_info, brk_data, brk_info

    def _make_bbox_from_center(self, cx, cy, radius_m):
        dlat_per_m = 1.0 / 111000.0
        dlon_per_m = 1.0 / (111000.0 * max(0.1, abs(math.cos(math.radians(cy)))))
        dlat = radius_m * dlat_per_m
        dlon = radius_m * dlon_per_m
        return {
            'type': 'Polygon',
            'coordinates': [[
                [cx - dlon, cy - dlat],
                [cx + dlon, cy - dlat],
                [cx + dlon, cy + dlat],
                [cx - dlon, cy + dlat],
                [cx - dlon, cy - dlat],
            ]]
        }

    # --------- Main ---------
    def analyze_line(self, line):
        """Analisi allerte deforestazione via GFW Data API (min area 4 ha di default; 'strict' o 'buffer')."""
        # prerequisiti
        self.check_prerequisites()
        api_key = self._get_api_key()
        ICP = self.env['ir.config_parameter'].sudo()
        origin = (ICP.get_param('planetio.gfw_api_origin') or 'http://localhost').strip()

        # parametri
        def _get_int(key, default):
            try:
                return int(ICP.get_param(key) or default)
            except Exception:
                return default

        def _get_float(key, default):
            try:
                return float(ICP.get_param(key) or default)
            except Exception:
                return default

        min_polygon_m   = _get_int('planetio.gfw_min_polygon_m', 60)
        min_area_ha_req = _get_float('planetio.gfw_min_area_ha', 4.0)  # default 4 ha
        area_policy     = (ICP.get_param('planetio.gfw_area_policy') or 'buffer').strip()  # 'buffer' | 'strict'
        if area_policy not in ('buffer', 'strict'):
            area_policy = 'buffer'

        second_buffer_m = _get_int('planetio.gfw_second_buffer_m', 150)
        diag_buffer_m   = _get_int('planetio.gfw_diag_buffer_m', 2000)
        auto_step_m     = _get_int('planetio.gfw_auto_buffer_step_m', 150)
        auto_max_m      = _get_int('planetio.gfw_auto_buffer_max_m', 2000)

        headers = self._prepare_headers(origin, api_key)
        debug_steps = []
        debug_errors = []

        def _integrated_with_variants(geom_to_use, start_date, allow_short_for_agg, variant_hint=None):
            variants = []
            if variant_hint:
                variants.append(variant_hint)
            variants.extend([
                ('alert__count', 'area__ha'),
                ('alerts__count', 'area__ha'),
            ])
            ordered = []
            seen = set()
            for item in variants:
                if not item or item in seen:
                    continue
                ordered.append(item)
                seen.add(item)

            last_error = None
            for idx, (count_field, area_field) in enumerate(ordered):
                try:
                    data = self._run_integrated_all_best_effort(
                        headers,
                        geom_to_use,
                        start_date,
                        debug_errors,
                        allow_short_for_agg=allow_short_for_agg,
                        count_field=count_field,
                        area_field=area_field,
                    )
                    return (count_field, area_field), data
                except UserError as ex:
                    last_error = ex
                    msg_lower = tools.ustr(ex).lower()
                    needs_fallback = any(token in msg_lower for token in ('alert__count', 'alerts__count'))
                    if needs_fallback and idx + 1 < len(ordered):
                        next_variant = ordered[idx + 1]
                        debug_errors.append(
                            f"count_field_fallback:{count_field}->{next_variant[0]}"
                        )
                        continue
                    raise

            if last_error:
                raise last_error
            raise UserError(_("Provider gfw: nessuna variante campo disponibile"))

        # geometria di input
        geom = self._extract_geometry(line)
        if not geom:
            raise UserError(_("Manca geometria (GeoJSON o lat/lon) sulla riga %s") %
                            (getattr(line, 'display_name', None) or line.id))
        original_geom = geom
        buffer_info = None

        # normalizzazione richiesta + enforcement area minima
        if geom.get('type') == 'Point':
            bbox = self._expand_point_to_bbox(geom)
            geom_req = bbox if bbox else geom
            geometry_mode = 'point_bbox' if bbox else 'point'
        elif geom.get('type') == 'Polygon':
            geom_buf, changed, info = self._maybe_buffer_tiny_polygon(
                geom, min_m=min_polygon_m, min_area_ha=min_area_ha_req, area_policy=area_policy
            )
            buffer_info = info
            # STRICT: se sotto soglia, fermiamo con messaggio esplicito
            if info and info.get('too_small_strict'):
                raise UserError(_(
                    "La geometria è inferiore alla soglia minima di %(minha).2f ha (modalità strict). "
                    "Area stimata ~%(m2).0f m². Aumenta l’area o passa alla modalità 'buffer' nelle Impostazioni."
                ) % {'minha': float(min_area_ha_req), 'm2': float(info.get('area_m2') or 0.0)})
            geom_req = geom_buf
            geometry_mode = 'polygon_buffered' if changed else 'polygon'
        else:
            geom_req = geom
            geometry_mode = 'original'

        # finestra temporale
        date_from = self._compute_date_from()

        field_variant_tuple = None

        # ---- Primo pass Integrated (aggregate hard, serie/brk best-effort)
        debug_steps.append({'step': 'integrated_initial', 'geom': self._bbox_hint(geom_req)})
        field_variant_tuple, integrated_data = _integrated_with_variants(
            geom_req, date_from, allow_short_for_agg=True, variant_hint=None
        )
        agg_data, agg_info, ser_data, ser_info, brk_data, brk_info = integrated_data
        row = (agg_data.get('data') or [{}])[0]
        alert_count = self._extract_number(row, ['alert_count', 'cnt', 'count']) or 0.0
        area_total  = self._extract_number(row, ['area_ha_total', 'area_ha', 'area']) or 0.0
        first_alert = self._extract_text(row, ['first_alert_date'])
        last_alert  = self._extract_text(row, ['last_alert_date'])

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
        final_geom_used = geom_req

        # ---- Secondo pass (se zero)
        second_pass_used = False
        second_pass_geom = None
        if alert_count == 0 and area_total == 0.0 and isinstance(second_buffer_m, int) and second_buffer_m > 0:
            try:
                if geom_req.get('type') == 'Polygon':
                    ring = geom_req['coordinates'][0]
                    lons = [p[0] for p in ring]; lats = [p[1] for p in ring]
                    cx = (min(lons) + max(lons)) / 2.0
                    cy = (min(lats) + max(lats)) / 2.0
                elif geom_req.get('type') == 'Point':
                    cx, cy = geom_req['coordinates'][0], geom_req['coordinates'][1]
                else:
                    cx = cy = None

                if cx is not None:
                    second_pass_geom = self._make_bbox_from_center(cx, cy, second_buffer_m)
                    debug_steps.append({'step': 'integrated_second_pass', 'geom': self._bbox_hint(second_pass_geom)})
                    field_variant_tuple, integrated_second = _integrated_with_variants(
                        second_pass_geom, date_from, allow_short_for_agg=True, variant_hint=field_variant_tuple
                    )
                    agg2, info2, ser2, info_ser2, brk2, info_brk2 = integrated_second
                    row2 = (agg2.get('data') or [{}])[0]
                    a2 = self._extract_number(row2, ['alert_count', 'cnt', 'count']) or 0.0
                    area2 = self._extract_number(row2, ['area_ha_total', 'area_ha', 'area']) or 0.0
                    second_pass_used = True
                    if a2 > 0 or area2 > 0:
                        agg_data, agg_info = agg2, info2
                        ser_data, ser_info = ser2, info_ser2
                        brk_data, brk_info = brk2, info_brk2
                        alert_count, area_total = a2, area2
                        first_alert = self._extract_text(row2, ['first_alert_date'])
                        last_alert  = self._extract_text(row2, ['last_alert_date'])
                        series_entries = _series_to_entries(ser2)
                        final_geom_used = second_pass_geom
            except Exception as ex:
                debug_errors.append(f"second_pass_error: {tools.ustr(ex)}")

        # ---- Auto buffer a step + tentativo su diag_buffer_m (aggregate hard)
        auto_buffer_geom = None
        auto_buffer_radius_m = None
        if alert_count == 0 and area_total == 0.0 and auto_max_m > 0 and auto_step_m > 0:
            try:
                base = second_pass_geom if second_pass_used and second_pass_geom else geom_req
                if base.get('type') == 'Polygon':
                    ring = base['coordinates'][0]
                    lons = [p[0] for p in ring]; lats = [p[1] for p in ring]
                    cx = (min(lons) + max(lons)) / 2.0
                    cy = (min(lats) + max(lats)) / 2.0
                elif base.get('type') == 'Point':
                    cx, cy = base['coordinates'][0], base['coordinates'][1]
                else:
                    cx = cy = None

                if cx is not None and cy is not None:
                    radius = max(second_buffer_m or 0, auto_step_m)
                    while radius <= auto_max_m:
                        test_geom = self._make_bbox_from_center(cx, cy, radius)
                        debug_steps.append({'step': 'integrated_auto_buffer_try', 'r': radius, 'geom': self._bbox_hint(test_geom)})
                        aggX, infoX = self._run_aggregate_on_dataset(headers, test_geom, date_from, 'gfw_integrated_alerts')
                        rowX = (aggX.get('data') or [{}])[0]
                        aX = self._extract_number(rowX, ['alert_count', 'cnt', 'count']) or 0.0
                        arX = self._extract_number(rowX, ['area_ha_total', 'area_ha', 'area']) or 0.0
                        if aX > 0 or arX > 0:
                            serX, info_serX, brkX, info_brkX = self._run_series_breakdown_best_effort(
                                headers, test_geom, infoX['date_from'], 'gfw_integrated_alerts', debug_errors
                            )
                            agg_data, agg_info = aggX, infoX
                            ser_data, ser_info = serX, info_serX
                            brk_data, brk_info = brkX, info_brkX
                            alert_count, area_total = aX, arX
                            first_alert = self._extract_text(rowX, ['first_alert_date'])
                            last_alert  = self._extract_text(rowX, ['last_alert_date'])
                            series_entries = _series_to_entries(serX)
                            auto_buffer_geom = test_geom
                            auto_buffer_radius_m = radius
                            final_geom_used = test_geom
                            break
                        radius += auto_step_m

                    if (alert_count == 0 and area_total == 0.0) and diag_buffer_m and diag_buffer_m > 0:
                        test_geom = self._make_bbox_from_center(cx, cy, diag_buffer_m)
                        debug_steps.append({'step': 'integrated_auto_buffer_diag_radius', 'r': diag_buffer_m, 'geom': self._bbox_hint(test_geom)})
                        aggX, infoX = self._run_aggregate_on_dataset(headers, test_geom, date_from, 'gfw_integrated_alerts')
                        rowX = (aggX.get('data') or [{}])[0]
                        aX = self._extract_number(rowX, ['alert_count', 'cnt', 'count']) or 0.0
                        arX = self._extract_number(rowX, ['area_ha_total', 'area_ha', 'area']) or 0.0
                        if aX > 0 or arX > 0:
                            serX, info_serX, brkX, info_brkX = self._run_series_breakdown_best_effort(
                                headers, test_geom, infoX['date_from'], 'gfw_integrated_alerts', debug_errors
                            )
                            agg_data, agg_info = aggX, infoX
                            ser_data, ser_info = serX, info_serX
                            brk_data, brk_info = brkX, info_brkX
                            alert_count, area_total = aX, arX
                            first_alert = self._extract_text(rowX, ['first_alert_date'])
                            last_alert  = self._extract_text(rowX, ['last_alert_date'])
                            series_entries = _series_to_entries(serX)
                            auto_buffer_geom = test_geom
                            auto_buffer_radius_m = diag_buffer_m
                            final_geom_used = test_geom
            except Exception as ex:
                debug_errors.append(f"auto_buffer_error: {tools.ustr(ex)}")

        # ---- Breakdown coerente con i dati correnti (già best-effort)
        breakdown_entries = []
        for rowB in (brk_data.get('data') or []):
            date_token = self._extract_text(rowB, ['alert_date', 'gfw_integrated_alerts__date', 'date'])
            if not date_token:
                continue
            breakdown_entries.append({
                'date': date_token,
                'alert_id': self._extract_text(rowB, ['alert_id', 'alert__id', 'cartodb_id', 'id']),
                'alert_count': self._extract_number(rowB, ['alert_count', 'count', 'cnt']) or 0.0,
                'area_ha': self._extract_number(rowB, ['area_ha', 'area', 'area_ha_total']) or 0.0,
                'confidence': self._extract_text(rowB, [
                    'confidence',
                    'gfw_integrated_alerts__confidence',
                    'umd_glad_sentinel2_alerts__confidence',
                    'umd_glad_landsat_alerts__confidence',
                    'wur_radd_alerts__confidence',
                ]),
            })

        # ---- Diagnostica + PROMOTION (se ancora zero) — aggregate hard, serie/brk best-effort
        diagnostics = None
        promotion_used = False
        promotion_reason = None
        promotion_geom = None
        if (alert_count == 0 and area_total == 0.0) and diag_buffer_m and diag_buffer_m > 0:
            try:
                base_for_diag = auto_buffer_geom or second_pass_geom or geom_req
                cx = cy = None
                if base_for_diag.get('type') == 'Polygon':
                    ring = base_for_diag['coordinates'][0]
                    lons = [p[0] for p in ring]; lats = [p[1] for p in ring]
                    cx = (min(lons) + max(lons)) / 2.0
                    cy = (min(lats) + max(lats)) / 2.0
                elif base_for_diag.get('type') == 'Point':
                    cx, cy = base_for_diag['coordinates'][0], base_for_diag['coordinates'][1]

                if cx is not None and cy is not None:
                    diagnostics = self._diag_nearby_sources(headers, cx, cy, diag_buffer_m, agg_info.get('date_from') or date_from)
                    debug_steps.append({'step': 'diagnostics', 'geom': self._bbox_hint(diagnostics.get('geometry'))})
                    diag_geom = diagnostics.get('geometry')

                    byds = diagnostics.get('by_dataset') or {}
                    ds_counts = [
                        ('gfw_integrated_alerts',     'Integrated', byds.get('Integrated', {}).get('count') or 0),
                        ('umd_glad_sentinel2_alerts', 'GLAD_S2',    byds.get('GLAD_S2',    {}).get('count') or 0),
                        ('wur_radd_alerts',           'RADD',       byds.get('RADD',       {}).get('count') or 0),
                        ('umd_glad_landsat_alerts',   'GLAD_L',     byds.get('GLAD_L',     {}).get('count') or 0),
                    ]
                    ds_counts = [c for c in ds_counts if c[2] > 0]
                    ds_counts.sort(key=lambda x: x[2], reverse=True)

                    for ds_id, _lbl, _cnt in ds_counts:
                        debug_steps.append({'step': 'promotion_dataset_first', 'dataset': ds_id, 'geom': self._bbox_hint(diag_geom)})

                        try:
                            aggD, infoD = self._run_aggregate_on_dataset(headers, diag_geom, agg_info.get('date_from') or date_from, ds_id)
                        except Exception as ex:
                            debug_errors.append(f"promotion_aggregate_error[{ds_id}]: {tools.ustr(ex)}")
                            continue

                        rowD = (aggD.get('data') or [{}])[0]
                        aD = self._extract_number(rowD, ['alert_count', 'cnt', 'count']) or 0.0
                        areaD = self._extract_number(rowD, ['area_ha_total', 'area_ha', 'area']) or 0.0

                        if aD > 0 or areaD > 0:
                            serD, info_serD, brkD, info_brkD = self._run_series_breakdown_best_effort(
                                headers, diag_geom, infoD['date_from'], ds_id, debug_errors
                            )
                            agg_data, agg_info = aggD, infoD
                            ser_data, ser_info = serD, info_serD
                            brk_data, brk_info = brkD, info_brkD
                            alert_count, area_total = aD, areaD
                            first_alert = self._extract_text(rowD, ['first_alert_date'])
                            last_alert  = self._extract_text(rowD, ['last_alert_date'])
                            series_entries = _series_to_entries(serD)
                            breakdown_entries = []
                            for rr in (brkD.get('data') or []):
                                dt = self._extract_text(rr, ['alert_date', 'date'])
                                if dt:
                                    breakdown_entries.append({
                                        'date': dt,
                                        'alert_id': self._extract_text(rr, ['alert_id', 'alert__id', 'cartodb_id', 'id']),
                                        'alert_count': self._extract_number(rr, ['alert_count','count','cnt']) or 0.0,
                                        'area_ha': self._extract_number(rr, ['area_ha','area','area_ha_total']) or 0.0,
                                        'confidence': None,
                                    })
                            promotion_used = True
                            promotion_reason = f'dataset_first:{ds_id}'
                            promotion_geom = diag_geom
                            used_dataset = ds_id
                            final_geom_used = diag_geom

                            if ds_id != 'gfw_integrated_alerts':
                                try:
                                    debug_steps.append({'step': 'promotion_reconcile_integrated', 'geom': self._bbox_hint(diag_geom)})
                                    aggR, infoR = self._run_aggregate_on_dataset(headers, diag_geom, infoD['date_from'], 'gfw_integrated_alerts')
                                    rowR = (aggR.get('data') or [{}])[0]
                                    aR = self._extract_number(rowR, ['alert_count', 'cnt', 'count']) or 0.0
                                    areaR = self._extract_number(rowR, ['area_ha_total', 'area_ha', 'area']) or 0.0
                                    if aR > 0 or areaR > 0:
                                        serR, info_serR, brkR, info_brkR = self._run_series_breakdown_best_effort(
                                            headers, diag_geom, infoR['date_from'], 'gfw_integrated_alerts', debug_errors
                                        )
                                        agg_data, agg_info = aggR, infoR
                                        ser_data, ser_info = serR, info_serR
                                        brk_data, brk_info = brkR, info_brkR
                                        alert_count, area_total = aR, areaR
                                        first_alert = self._extract_text(rowR, ['first_alert_date'])
                                        last_alert  = self._extract_text(rowR, ['last_alert_date'])
                                        series_entries = _series_to_entries(serR)
                                        breakdown_entries = []
                                        for rr in (brkR.get('data') or []):
                                            dt = self._extract_text(rr, ['alert_date', 'date'])
                                            if dt:
                                                breakdown_entries.append({
                                                    'date': dt,
                                                    'alert_id': self._extract_text(rr, ['alert_id', 'alert__id', 'cartodb_id', 'id']),
                                                    'alert_count': self._extract_number(rr, ['alert_count','count','cnt']) or 0.0,
                                                    'area_ha': self._extract_number(rr, ['area_ha','area','area_ha_total']) or 0.0,
                                                    'confidence': self._extract_text(rr, ['confidence','gfw_integrated_alerts__confidence']),
                                                })
                                        used_dataset = 'gfw_integrated_alerts'
                                        promotion_reason = 'reconciled_to_integrated'
                                except Exception as ex:
                                    debug_errors.append(f"promotion_reconcile_error: {tools.ustr(ex)}")
                            break
            except Exception as ex:
                debug_errors.append(f"promotion_block_error: {tools.ustr(ex)}")

        details_data = {'data': []}
        details_info = {'endpoint': None, 'date_from': agg_info.get('date_from') or date_from, 'dataset': used_dataset}
        try:
            details_data, details_info = self._run_alert_details_best_effort(
                headers,
                final_geom_used or geom_req,
                agg_info.get('date_from') or date_from,
                used_dataset,
                debug_errors,
            )
        except Exception as ex:
            debug_errors.append(f"details_error[{used_dataset}]: {tools.ustr(ex)}")
            details_data = {'data': []}
            details_info = {'endpoint': None, 'date_from': agg_info.get('date_from') or date_from, 'dataset': used_dataset}

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
            detail_entries.append({
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
                'latitude': self._extract_number(rowD, ['latitude', 'lat', 'alert_lat', 'alert__lat', 'y']),
                'longitude': self._extract_number(rowD, ['longitude', 'lon', 'lng', 'alert_lon', 'alert__lon', 'x']),
            })

        if detail_entries:
            breakdown_entries = detail_entries

        # ---- Rolling 30/90 giorni
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

        field_variant_meta = {
            'count': field_variant_tuple[0] if field_variant_tuple else 'COUNT(*)',
            'area': field_variant_tuple[1] if field_variant_tuple else 'area__ha',
        }

        meta = {
            'provider': 'gfw',
            'date_from': agg_info.get('date_from') or date_from,
            'dataset_endpoint': agg_info.get('endpoint'),
            'geometry_mode': geometry_mode,
            'buffer_info': buffer_info,
            'second_pass': {
                'used': bool(second_pass_used),
                'buffer_m': second_buffer_m if second_pass_used else None,
                'geom': second_pass_geom if second_pass_used else None,
            },
            'auto_buffer': {
                'used': bool(auto_buffer_geom),
                'radius_m': auto_buffer_radius_m,
                'geom': auto_buffer_geom,
                'step_m': auto_step_m,
                'max_m': auto_max_m,
            } if auto_buffer_geom else None,
            'diagnostics': diagnostics,
            'promotion': {
                'used': bool(promotion_used),
                'reason': promotion_reason,
                'geom': promotion_geom,
            },
            'snap': {'used': False, 'source': None, 'bbox_m': None, 'geom': None},
            'used_dataset': used_dataset,
            'field_variant': field_variant_meta,
            'queries': {
                'aggregate': agg_info,
                'time_series': ser_info,
                'breakdown': brk_info,
                'details': details_info,
            },
            'original_geom': original_geom,
            'final_geom_used': final_geom_used,
            'debug': {
                'steps': debug_steps,
                'errors': debug_errors,
                'final_geom_hint': self._bbox_hint(final_geom_used),
            }
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
