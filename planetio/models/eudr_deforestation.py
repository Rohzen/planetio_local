# -*- coding: utf-8 -*-
import json
import math
import requests
import traceback
from datetime import date, timedelta

import traceback
from collections import defaultdict

from odoo import models, fields, api, _, tools
from odoo.exceptions import UserError


class EUDRDeclarationLineDeforestation(models.Model):
    _inherit = "eudr.declaration.line"

    defor_provider = fields.Char(string="Deforestation Provider", readonly=True)
    defor_alerts = fields.Integer(string="Deforestation Alerts", readonly=True)
    defor_area_ha = fields.Float(string="Deforestation Area (ha)", readonly=True)
    defor_details_json = fields.Text(string="Deforestation Details (JSON)", readonly=True)

    # ---------- Geometry helpers ----------
    def _line_geometry(self):
        """Return a GeoJSON geometry for this line.
        Priority: geometry_geojson -> geometry -> geojson -> geometry_json.
        If a Point is provided it is returned as-is. If only lat/lon are available
        a Point geometry is built.
        """
        self.ensure_one()
        field_candidates = ['geometry_geojson', 'geometry', 'geojson', 'geometry_json']
        for fname in field_candidates:
            if fname in self._fields:
                val = getattr(self, fname)
                if val:
                    try:
                        g = json.loads(val) if isinstance(val, str) else val
                    except Exception:
                        g = None
                    if isinstance(g, dict) and g.get('type'):
                        return g

        # Fallback to latitude/longitude aliases
        lat_keys = ['lat', 'latitude', 'lat_dd']
        lon_keys = ['lon', 'longitude', 'lng', 'long_dd']
        lat = None
        lon = None
        for k in lat_keys:
            if k in self._fields and getattr(self, k):
                lat = getattr(self, k)
                break
        for k in lon_keys:
            if k in self._fields and getattr(self, k):
                lon = getattr(self, k)
                break
        if lat is not None and lon is not None:
            return {'type': 'Point', 'coordinates': [lon, lat]}
        return None

    def _geom_bbox(self, geom):
        try:
            t = geom.get('type')
            coords = []
            if t == 'Polygon':
                for ring in geom.get('coordinates', []):
                    coords += ring
            elif t == 'MultiPolygon':
                for poly in geom.get('coordinates', []):
                    for ring in poly:
                        coords += ring
            elif t == 'Point':
                lon, lat = geom.get('coordinates', [None, None])
                if lon is None or lat is None:
                    return None
                dlat = 0.2 / 111.0
                dlon = 0.2 / (111.0 * max(0.1, abs(math.cos(math.radians(lat)))))
                return {'type':'Polygon','coordinates':[[
                    [lon-dlon, lat-dlat],[lon+dlon, lat-dlat],[lon+dlon, lat+dlat],[lon-dlon, lat+dlat],[lon-dlon, lat-dlat]
                ]]}
            else:
                return None
            if not coords:
                return None
            lons = [pt[0] for pt in coords if isinstance(pt, (list, tuple)) and len(pt) >= 2]
            lats = [pt[1] for pt in coords if isinstance(pt, (list, tuple)) and len(pt) >= 2]
            if not lons or not lats:
                return None
            minx, maxx = min(lons), max(lons)
            miny, maxy = min(lats), max(lats)
            return {'type': 'Polygon', 'coordinates': [[
                [minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy], [minx, miny]
            ]]}
        except Exception:
            return None

    # ---------- Fallback direct to GFW ----------
    def _gfw_analyze_fallback(self):
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        api_key = (ICP.get_param('planetio.gfw_api_key') or '').strip()
        if not api_key:
            raise UserError(_('Configura planetio.gfw_api_key'))
        origin = (ICP.get_param('planetio.gfw_api_origin') or 'http://localhost').strip()
        try:
            days_back = int(ICP.get_param('planetio.gfw_days_back') or 365)
        except Exception:
            days_back = 365
        date_from = (date.today() - timedelta(days=days_back)).isoformat()

        geom = self._line_geometry()
        if not geom:
            raise UserError(_('Manca geometria (GeoJSON o lat/lon) sulla riga %s') % (getattr(self,'display_name',None) or self.id))

        # The GFW Data API requires a Polygon/MultiPolygon for raster analysis;
        # if a Point is provided, automatically expand it to a small bounding box
        # around the point to allow the request to succeed.
        bbox = self._geom_bbox(geom)
        geom_req = geom
        step = 'latest/original'
        if geom.get('type') == 'Point' and bbox:
            geom_req = bbox
            step = 'latest/bbox'

        url_latest = 'https://data-api.globalforestwatch.org/dataset/gfw_integrated_alerts/latest/query/json'
        sql = "SELECT COUNT(*) AS cnt FROM results WHERE gfw_integrated_alerts__date >= '%s'" % date_from
        headers = {'x-api-key': api_key, 'Content-Type': 'application/json', 'Origin': origin}

        # Try 1: geometry (possibly expanded to bbox)
        body = {'sql': sql, 'geometry': geom_req}
        r = requests.post(url_latest, headers=headers, json=body, timeout=60)

        # Fallbacks for 500
        if r.status_code >= 500 and bbox and geom_req is not bbox:
            r = requests.post(url_latest, headers=headers, json={'sql': sql, 'geometry': bbox}, timeout=60)
            step = 'latest/bbox'

        if r.status_code >= 500:
            short_from = (date.today() - timedelta(days=min(90, days_back))).isoformat()
            sql_short = "SELECT COUNT(*) AS cnt FROM results WHERE gfw_integrated_alerts__date >= '%s'" % short_from
            if step.endswith('bbox'):
                r = requests.post(url_latest, headers=headers, json={'sql': sql_short, 'geometry': bbox}, timeout=60)
                step = 'latest/bbox/90d'
            else:
                r = requests.post(url_latest, headers=headers, json={'sql': sql_short, 'geometry': geom_req}, timeout=60)
                step = 'latest/original/90d'

        if r.status_code >= 500:
            url_ver = 'https://data-api.globalforestwatch.org/dataset/gfw_integrated_alerts/v20250909/query/json'
            if step.endswith('bbox'):
                r = requests.post(url_ver, headers=headers, json={'sql': sql, 'geometry': bbox}, timeout=60)
                step = 'version/bbox'
            else:
                r = requests.post(url_ver, headers=headers, json={'sql': sql, 'geometry': geom_req}, timeout=60)
                step = 'version/original'

        if r.status_code >= 400:
            snippet = (r.text or '')[:300]
            raise UserError(_("Data API HTTP %(code)s: step=%(s)s; body=%(b)s") % {'code': r.status_code, 's': step, 'b': snippet})

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

        return {
            'message': _("GFW Data API: %(n)s allerta/e (da %(d)s)") % {'n': cnt, 'd': date_from},
            'metrics': {'alert_count': cnt, 'area_ha_total': 0.0},
            'meta': {'provider': 'gfw', 'date_from': date_from, 'step': step},
        }

    # ---------- Public: invoked by button on line ----------
    def action_analyze_deforestation(self):
        # self can be either lines or declarations; normalize to lines
        lines = self
        if self._name == 'eudr.declaration':
            lines = self.mapped('line_ids')

        # run analyses and collect results grouped by declaration
        grouped = defaultdict(list)

        for line in lines:
            try:
                svc = line.env.get('planetio.deforestation.service') or line.env.get('deforestation.service')
                if svc and hasattr(svc, 'analyze_line'):
                    status = svc.analyze_line(line)
                elif svc and hasattr(svc, 'analyze_geojson'):
                    status = svc.analyze_geojson(line._line_geometry() or {})
                else:
                    status = line._gfw_analyze_fallback()

                # write computed fields if present
                if isinstance(status, dict):
                    metrics = status.get('metrics') or {}
                    vals = {}
                    if 'defor_provider' in line._fields:
                        vals['defor_provider'] = (status.get('meta') or {}).get('provider', 'gfw')
                    if 'defor_alerts' in line._fields and 'alert_count' in metrics:
                        vals['defor_alerts'] = metrics.get('alert_count') or 0
                    if 'defor_area_ha' in line._fields and 'area_ha_total' in metrics:
                        vals['defor_area_ha'] = metrics.get('area_ha_total') or 0.0
                    if 'defor_details_json' in line._fields:
                        try:
                            vals['defor_details_json'] = json.dumps(status, ensure_ascii=False)
                        except Exception:
                            vals['defor_details_json'] = tools.ustr(status)
                    if 'external_ok' in line._fields and metrics.get('alert_count', 0) > 0:
                        vals['external_ok'] = False
                    else:
                        vals['external_ok'] = True
                    if vals:
                        line.write(vals)

                # friendly, short per-line snippet for later batching
                if isinstance(status, dict):
                    msg = status.get('message') or tools.ustr(status)
                else:
                    msg = tools.ustr(status)

                grouped[line.declaration_id.id].append({
                    'line': line,
                    'ok': True,
                    'msg': msg,
                })

            except Exception as e:
                last = ''.join(traceback.format_exception_only(type(e), e)).strip()
                grouped[line.declaration_id.id].append({
                    'line': line,
                    'ok': False,
                    'msg': _("Analisi deforestazione fallita sulla riga %(name)s: %(err)s") % {
                        'name': (getattr(line, 'display_name', None) or line.id),
                        'err': tools.ustr(last or e),
                    }
                })
                # keep going

        # post one message per declaration
        Declaration = lines.env['eudr.declaration']
        for decl_id, items in grouped.items():
            decl = Declaration.browse(decl_id)
            # build an HTML body with line links for easier navigation
            lis = []
            for it in items:
                line = it['line']
                anchor = "/web#id=%s&model=%s&view_type=form" % (line.id, line._name)
                prefix = "OK" if it['ok'] else "ERRORE"
                # escape user-facing text
                line_name = tools.html_escape(getattr(line, 'display_name', str(line.id)))
                msg_txt = tools.html_escape(it['msg'])
                lis.append(
                    '<li>[%s] <a href="%s">%s</a>: %s</li>' % (prefix, anchor, line_name, msg_txt)
                )
            body = "<p>Risultati analisi deforestazione</p><ul>%s</ul>" % ''.join(lis)

            # one chatter message on the parent
            decl.message_post(
                body=body,
                message_type='comment',
                subtype_xmlid='mail.mt_note',
            )

        return True


class EUDRDeclarationDeforestation(models.Model):
    _inherit = "eudr.declaration"

    def action_analyze_deforestation(self):
        for decl in self:
            lines = decl.mapped('line_ids') if hasattr(decl, 'line_ids') else self.env['eudr.declaration.line'].search([('declaration_id','=',decl.id)])
            for line in lines:
                try:
                    line.action_analyze_deforestation()
                except Exception as e:
                    last = ''.join(traceback.format_exception_only(type(e), e)).strip()
                    try:
                        decl.message_post(body=_("Analisi deforestazione fallita sulla riga %(name)s: %(err)s") % {
                            'name': (getattr(line, 'display_name', None) or line.id),
                            'err': tools.ustr(last or e),
                        })
                    except Exception:
                        pass
                    continue
        return True
