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

    # Single source of truth
    def _get_api_key(self):
        icp = self.env['ir.config_parameter'].sudo()
        key = (icp.get_param('planetio.gfw_api_key') or '').strip()
        return key or None

    def check_prerequisites(self):
        if not self._get_api_key():
            raise UserError(_("GFW API Key mancante. Imposta 'GFW API Key' nelle Impostazioni."))

    # ----- helpers -----
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

    # ----- main API -----
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

    def _execute_sql(self, headers, geometry, sql_template, date_from, allow_short=True):
        base_url = 'https://data-api.globalforestwatch.org/dataset/gfw_integrated_alerts'
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
            details = "; ".join(
                f"{item['endpoint']} ({item.get('fallback', 'full')}): {item['status_code']}"
                for item in attempts
            )
            raise UserError(_("Provider gfw: nessuna risposta valida dal Data API (%s)") % details)

        return self._safe_json(version_resp), {
            'endpoint': 'v20250909',
            'date_from': date_from,
            'sql': sql_long,
            'status_code': version_resp.status_code,
            'fallback': 'version',
        }

    def analyze_line(self, line):
        """Esegue un'analisi avanzata sulle allerte di deforestazione via GFW Data API."""

        self.check_prerequisites()
        api_key = self._get_api_key()
        ICP = self.env['ir.config_parameter'].sudo()
        origin = (ICP.get_param('planetio.gfw_api_origin') or 'http://localhost').strip()

        geom = self._extract_geometry(line)
        if not geom:
            raise UserError(_("Manca geometria (GeoJSON o lat/lon) sulla riga %s") %
                            (getattr(line, 'display_name', None) or line.id))

        bbox = self._expand_point_to_bbox(geom) if geom.get('type') == 'Point' else None
        geom_req = bbox if bbox else geom

        date_from = self._compute_date_from()

        headers = self._prepare_headers(origin, api_key)

        aggregate_sql = (
            "SELECT "
            "SUM(alert__count) AS alert_count, "
            "SUM(alert__area__ha) AS area_ha_total, "
            "MIN(gfw_integrated_alerts__date) AS first_alert_date, "
            "MAX(gfw_integrated_alerts__date) AS last_alert_date "
            "FROM results WHERE gfw_integrated_alerts__date >= '{date_from}'"
        )

        series_sql = (
            "SELECT gfw_integrated_alerts__date AS alert_date, "
            "SUM(alert__count) AS alert_count, "
            "SUM(alert__area__ha) AS area_ha "
            "FROM results WHERE gfw_integrated_alerts__date >= '{date_from}' "
            "GROUP BY gfw_integrated_alerts__date "
            "ORDER BY alert_date DESC LIMIT 365"
        )

        breakdown_sql = (
            "SELECT gfw_integrated_alerts__date AS alert_date, "
            "SUM(alert__count) AS alert_count, "
            "SUM(alert__area__ha) AS area_ha, "
            "MAX(confidence__rating) AS confidence, "
            "MAX(alert__id) AS alert_id "
            "FROM results WHERE gfw_integrated_alerts__date >= '{date_from}' "
            "GROUP BY gfw_integrated_alerts__date "
            "ORDER BY alert_date DESC LIMIT 200"
        )

        aggregate_data, aggregate_info = self._execute_sql(headers, geom_req, aggregate_sql, date_from, allow_short=True)
        series_data, series_info = self._execute_sql(headers, geom_req, series_sql, aggregate_info['date_from'], allow_short=False)
        breakdown_data, breakdown_info = self._execute_sql(headers, geom_req, breakdown_sql, aggregate_info['date_from'], allow_short=False)

        aggregate_row = (aggregate_data.get('data') or [{}])[0]
        alert_count = self._extract_number(aggregate_row, ['alert_count', 'cnt', 'count']) or 0.0
        area_total = self._extract_number(aggregate_row, ['area_ha_total', 'area_ha', 'area']) or 0.0
        first_alert = self._extract_text(aggregate_row, ['first_alert_date'])
        last_alert = self._extract_text(aggregate_row, ['last_alert_date'])

        series_entries = []
        for row in series_data.get('data') or []:
            date_token = self._extract_text(row, ['alert_date', 'gfw_integrated_alerts__date', 'date'])
            if not date_token:
                continue
            series_entries.append({
                'date': date_token,
                'alert_count': self._extract_number(row, ['alert_count', 'count', 'cnt']) or 0.0,
                'area_ha': self._extract_number(row, ['area_ha', 'area', 'area_ha_total']) or 0.0,
            })

        breakdown_entries = []
        for row in breakdown_data.get('data') or []:
            date_token = self._extract_text(row, ['alert_date', 'gfw_integrated_alerts__date', 'date'])
            if not date_token:
                continue
            breakdown_entries.append({
                'date': date_token,
                'alert_id': self._extract_text(row, ['alert_id']),
                'alert_count': self._extract_number(row, ['alert_count', 'count', 'cnt']) or 0.0,
                'area_ha': self._extract_number(row, ['area_ha', 'area', 'area_ha_total']) or 0.0,
                'confidence': self._extract_text(row, ['confidence', 'confidence_rating', 'confidence__rating']),
            })

        def _sum_recent(days):
            cutoff = date.today() - timedelta(days=days)
            total_count = 0.0
            total_area = 0.0
            for entry in series_entries:
                entry_date = self._parse_iso_date(entry.get('date'))
                if entry_date and entry_date >= cutoff:
                    total_count += entry.get('alert_count') or 0.0
                    total_area += entry.get('area_ha') or 0.0
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

        message_parts = []
        if metrics['alert_count']:
            message_parts.append(
                _("GFW Data API: %(n)s allerta/e rilevate dal %(d)s")
                % {'n': metrics['alert_count'], 'd': aggregate_info['date_from']}
            )
        else:
            message_parts.append(
                _("GFW Data API: nessuna allerta rilevata dal %(d)s")
                % {'d': aggregate_info['date_from']}
            )
        if metrics['area_ha_total']:
            message_parts.append(
                _("Area interessata: %(area).2f ha") % {'area': metrics['area_ha_total']}
            )
        if last_alert:
            message_parts.append(_("Ultima allerta: %s") % last_alert)

        message = "; ".join(message_parts)

        meta = {
            'provider': 'gfw',
            'date_from': aggregate_info['date_from'],
            'dataset_endpoint': aggregate_info.get('endpoint'),
            'geometry_mode': 'bbox' if bbox else 'original',
            'queries': {
                'aggregate': aggregate_info,
                'time_series': series_info,
                'breakdown': breakdown_info,
            },
        }

        details = {
            'metrics': metrics,
            'alerts': breakdown_entries,
            'time_series': series_entries,
            'responses': {
                'aggregate': aggregate_data,
                'time_series': series_data,
                'breakdown': breakdown_data,
            },
        }

        return {
            'message': message,
            'alerts': breakdown_entries,
            'metrics': metrics,
            'meta': meta,
            'details': details,
        }
