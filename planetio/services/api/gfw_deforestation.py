# -*- coding: utf-8 -*-
import math
import requests
from datetime import date, timedelta
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
    def analyze_line(self, line):
        """Conta le allerte GFW sulla geometry della riga, usando il Data API (no gfw_client)."""
        self.check_prerequisites()
        api_key = self._get_api_key()
        ICP = self.env['ir.config_parameter'].sudo()
        origin = (ICP.get_param('planetio.gfw_api_origin') or 'http://localhost').strip()

        # 1) geometry
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
        if not isinstance(geom, dict) or not geom.get('type'):
            raise UserError(_("Manca geometria (GeoJSON o lat/lon) sulla riga %s") %
                            (getattr(line, 'display_name', None) or line.id))

        # 2) normalizza Point -> bbox
        step = 'latest/original'
        bbox = self._expand_point_to_bbox(geom) if geom.get('type') == 'Point' else None
        geom_req = bbox if bbox else geom
        if bbox:
            step = 'latest/bbox'

        # 3) finestra temporale
        date_from = self._compute_date_from()

        # 4) call Data API (stessa sequenza del fallback)
        url_latest = 'https://data-api.globalforestwatch.org/dataset/gfw_integrated_alerts/latest/query/json'
        sql = "SELECT COUNT(*) AS cnt FROM results WHERE gfw_integrated_alerts__date >= '%s'" % date_from
        headers = {'x-api-key': api_key, 'Content-Type': 'application/json', 'Origin': origin}

        # try 1
        body = {'sql': sql, 'geometry': geom_req}
        try:
            r = requests.post(url_latest, headers=headers, json=body, timeout=60)
        except requests.exceptions.RequestException as ex:
            raise UserError(_("Connessione a GFW non riuscita: %s") % tools.ustr(ex))

        # try 2: se 500, prova 90 giorni
        if r.status_code >= 500:
            short_from = (date.today() - timedelta(days=90)).isoformat()
            sql_short = "SELECT COUNT(*) AS cnt FROM results WHERE gfw_integrated_alerts__date >= '%s'" % short_from
            r = requests.post(url_latest, headers=headers, json={'sql': sql_short, 'geometry': geom_req}, timeout=60)
            step = step + '/90d'

        # try 3: versione fissa se ancora 500
        if r.status_code >= 500:
            url_ver = 'https://data-api.globalforestwatch.org/dataset/gfw_integrated_alerts/v20250909/query/json'
            r = requests.post(url_ver, headers=headers, json={'sql': sql, 'geometry': geom_req}, timeout=60)
            step = 'version/' + ('bbox' if bbox else 'original')

        if r.status_code >= 400:
            snippet = (r.text or '')[:300]
            raise UserError(_("Provider gfw: Richiesta rifiutata da GFW: %s") % tools.ustr(snippet or r.status_code))

        try:
            data = r.json()
        except Exception:
            data = {'data': []}

        rows = data.get('data') or []
        cnt = 0
        if rows and isinstance(rows[0], dict):
            try:
                cnt = int(rows[0].get('cnt') or 0)
            except Exception:
                cnt = 0

        # 5) risposta standardizzata (coerente col resto del modulo)
        return {
            'message': _("GFW Data API: %(n)s allerta/e (da %(d)s)") % {'n': cnt, 'd': date_from},
            'metrics': {'alert_count': cnt, 'area_ha_total': 0.0},
            'meta': {'provider': 'gfw', 'date_from': date_from, 'step': step},
        }
