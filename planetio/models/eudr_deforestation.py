# -*- coding: utf-8 -*-
import json
import math
import re
import requests
import traceback
from datetime import date, datetime, timedelta
from collections import defaultdict

from odoo import models, fields, api, _, tools
from odoo.exceptions import UserError


def _coerce_int(value):
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return None
        return int(round(value))
    if isinstance(value, str):
        raw = value.strip()
        if not raw or raw.lower() in {"nan", "none", "null"}:
            return None
        cleaned = re.sub(r"[^0-9.+-]", "", raw)
        if not cleaned:
            return None
        try:
            return int(round(float(cleaned)))
        except Exception:
            return None
    return None


def _coerce_float(value):
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        return float(value)
    if isinstance(value, str):
        raw = value.strip()
        if not raw or raw.lower() in {"nan", "none", "null"}:
            return None
        cleaned = re.sub(r"[^0-9.+-]", "", raw)
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except Exception:
            return None
    return None


def parse_deforestation_external_properties(raw_props):
    if not raw_props:
        return None

    if isinstance(raw_props, (bytes, bytearray)):
        try:
            raw_props = raw_props.decode("utf-8")
        except Exception:
            return None

    data = raw_props
    if isinstance(raw_props, str):
        try:
            data = json.loads(raw_props)
        except Exception:
            return None

    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                parsed = parse_deforestation_external_properties(item)
                if parsed:
                    return parsed
        return None

    if not isinstance(data, dict):
        return None

    candidates = [data]
    if isinstance(data.get("properties"), dict):
        candidates.append(data["properties"])

    known_keys = {
        "alert_count",
        "alertcount",
        "alert_count_total",
        "alert_count_7d",
        "alert_count_30d",
        "alerts",
        "alerts_total",
        "alerts_7d",
        "alerts_30d",
        "alertcount30d",
        "risk_level",
        "risk",
        "period",
        "last_alert",
        "last_alert_date",
    }

    chosen = None
    metrics_payload = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        metrics_candidate = candidate.get("metrics") if isinstance(candidate.get("metrics"), dict) else {}
        if any(key in candidate for key in known_keys) or metrics_candidate:
            chosen = candidate
            metrics_payload = metrics_candidate
            break

    if not chosen:
        return None

    count_keys = [
        "alert_count",
        "alert_count_total",
        "alerts_total",
        "alert_count_30d",
        "alerts_30d",
        "alert_count_7d",
        "alerts_7d",
        "alertcount",
        "alerts",
        "alertcount30d",
    ]

    counts = {}
    for key in count_keys:
        parsed = _coerce_int(chosen.get(key))
        if parsed is not None:
            counts[key] = parsed
            continue
        if key in metrics_payload:
            parsed = _coerce_int(metrics_payload.get(key))
            if parsed is not None:
                counts[key] = parsed

    risk_raw = chosen.get("risk_level") or chosen.get("risk") or metrics_payload.get("risk_level") or metrics_payload.get("risk")
    risk_label = str(risk_raw).strip() if risk_raw not in (None, "") else ""
    risk_token = risk_label.lower().replace(" ", "_").replace("-", "_") if risk_label else ""

    last_alert = (
        chosen.get("last_alert_date")
        or chosen.get("last_alert")
        or metrics_payload.get("last_alert_date")
        or metrics_payload.get("last_alert")
    )
    period = (
        chosen.get("period")
        or chosen.get("date_range")
        or metrics_payload.get("period")
        or metrics_payload.get("date_range")
    )

    if not counts and not (risk_label or last_alert or period):
        return None

    preferred_order = [
        "alert_count",
        "alert_count_total",
        "alerts_total",
        "alert_count_30d",
        "alerts_30d",
        "alert_count_7d",
        "alerts_7d",
        "alertcount",
        "alerts",
        "alertcount30d",
    ]

    alert_count = None
    alert_count_key = None
    for key in preferred_order:
        if key in counts:
            alert_count = counts[key]
            alert_count_key = key
            break
    if alert_count is None and counts:
        alert_count_key, alert_count = max(counts.items(), key=lambda item: item[1])

    area_keys = [
        "area_ha_total",
        "alert_area_ha",
        "area_ha",
        "area_hectares",
        "affected_area_ha",
    ]

    area_val = None
    for key in area_keys:
        parsed = _coerce_float(chosen.get(key))
        if parsed is None and key in metrics_payload:
            parsed = _coerce_float(metrics_payload.get(key))
        if parsed is not None:
            area_val = parsed
            break

    metrics = {}
    for key, value in counts.items():
        metrics[key] = value
    metrics['alert_count'] = alert_count or 0
    metrics['area_ha_total'] = area_val if area_val is not None else 0.0

    source = (
        chosen.get("source")
        or chosen.get("provider")
        or metrics_payload.get("source")
        or metrics_payload.get("provider")
    )
    confidence = chosen.get("confidence") or metrics_payload.get("confidence")
    primary_drivers = chosen.get("primary_drivers") or metrics_payload.get("primary_drivers")
    notes = chosen.get("notes") or metrics_payload.get("notes")

    risky_levels = {
        "critical",
        "very_high",
        "veryhigh",
        "high",
        "medium",
        "elevated",
        "extreme",
        "very_high_risk",
    }
    risk_flag = False
    if alert_count and alert_count > 0:
        risk_flag = True
    elif risk_token in risky_levels:
        risk_flag = True

    info_parts = []
    if alert_count is not None:
        info_parts.append(_("alerts: %(count)s") % {"count": alert_count})
    if risk_label:
        info_parts.append(_("risk: %(risk)s") % {"risk": risk_label})
    if period:
        info_parts.append(_("period: %(period)s") % {"period": period})
    if last_alert:
        info_parts.append(_("last alert: %(last)s") % {"last": last_alert})

    if info_parts:
        message = _("GeoJSON deforestation data (%(details)s)") % {"details": "; ".join(info_parts)}
    else:
        message = _("GeoJSON deforestation data")

    meta = {"provider": "gfw", "risk_flag": bool(risk_flag)}
    if source:
        meta["source"] = source
    if risk_token:
        meta["risk_level"] = risk_token
    if risk_label and risk_label.lower() != risk_token:
        meta["risk_level_label"] = risk_label
    if alert_count_key:
        meta["alert_count_key"] = alert_count_key
    if period:
        meta["period"] = period
    if last_alert:
        meta["last_alert_date"] = last_alert
    if confidence:
        meta["confidence"] = confidence
    if primary_drivers:
        meta["primary_drivers"] = primary_drivers
    if notes:
        meta["notes"] = notes

    details = {"externalProperties": chosen}
    if counts:
        details["alertCounts"] = counts

    return {
        "message": message,
        "metrics": metrics,
        "meta": meta,
        "details": details,
    }


class EUDRDeclarationLineAlert(models.Model):
    _name = "eudr.declaration.line.alert"
    _description = "EUDR Declaration Line Deforestation Alert"
    _order = "alert_date desc, id desc"

    name = fields.Char(string="Description")
    line_id = fields.Many2one(
        "eudr.declaration.line",
        string="Declaration Line",
        required=True,
        ondelete="cascade",
        index=True,
    )
    provider = fields.Char(string="Provider")
    alert_identifier = fields.Char(string="Alert Identifier")
    alert_date = fields.Date(string="Alert Date")
    alert_date_raw = fields.Char(string="Alert Date (raw)")
    risk_level = fields.Char(string="Risk Level")
    confidence = fields.Char(string="Confidence")
    area_ha = fields.Float(string="Area (ha)")
    latitude = fields.Float(string="Latitude")
    longitude = fields.Float(string="Longitude")
    problem_description = fields.Text(string="Problem Description")
    payload_json = fields.Text(string="Raw Payload", readonly=True)


class EUDRDeclarationLineDeforestation(models.Model):
    _inherit = "eudr.declaration.line"

    defor_provider = fields.Char(string="Deforestation Provider", readonly=True)
    defor_alerts = fields.Integer(string="Deforestation Alerts", readonly=True)
    defor_area_ha = fields.Float(string="Deforestation Area (ha)", readonly=True)
    defor_details_json = fields.Text(string="Deforestation Details (JSON)", readonly=True)
    alert_ids = fields.One2many(
        "eudr.declaration.line.alert",
        "line_id",
        string="Deforestation Alerts",
        readonly=True,
    )

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

    def _get_deforestation_service(self):
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        provider_code = (ICP.get_param('planetio.deforestation_provider') or 'gfw').strip() or 'gfw'
        if 'deforestation.service' in self.env:
            return self.env['deforestation.service'].with_context(deforestation_providers_override=[provider_code])
        return None

    # ---------- Public: invoked by button on line ----------
    def retrieve_deforestation_status(self):
        """Return the latest deforestation status payload for the line.

        The method is side-effect free and can be reused by callers that
        need to inspect the alerts without triggering the chatter updates
        performed by :meth:`action_analyze_deforestation`.
        """

        self.ensure_one()

        status = parse_deforestation_external_properties(
            getattr(self, 'external_properties_json', None)
        )
        if status:
            return status

        svc = self._get_deforestation_service()
        if svc is not None and hasattr(svc, 'analyze_line'):
            return svc.analyze_line(self)
        if svc is not None and hasattr(svc, 'analyze_geojson'):
            return svc.analyze_geojson(self._line_geometry() or {})
        return self._gfw_analyze_fallback()

    def _apply_deforestation_status(self, status):
        if not isinstance(status, dict):
            return

        metrics = status.get('metrics') or {}
        vals = {}
        if 'defor_provider' in self._fields:
            vals['defor_provider'] = (status.get('meta') or {}).get('provider', 'gfw')
        if 'defor_alerts' in self._fields and 'alert_count' in metrics:
            vals['defor_alerts'] = metrics.get('alert_count') or 0
        if 'defor_area_ha' in self._fields and 'area_ha_total' in metrics:
            vals['defor_area_ha'] = metrics.get('area_ha_total') or 0.0
        if 'defor_details_json' in self._fields:
            try:
                vals['defor_details_json'] = json.dumps(status, ensure_ascii=False)
            except Exception:
                vals['defor_details_json'] = tools.ustr(status)
        if 'external_ok' in self._fields:
            risk_flag = False
            if metrics.get('alert_count', 0) > 0:
                risk_flag = True
            elif isinstance(status.get('meta'), dict):
                risk_flag = bool(status['meta'].get('risk_flag'))
            vals['external_ok'] = not risk_flag
        if vals:
            self.write(vals)
        self._sync_alert_records_from_status(status)

    def action_analyze_deforestation(self):
        # self can be either lines or declarations; normalize to lines
        lines = self
        if self._name == 'eudr.declaration':
            lines = self.mapped('line_ids')

        # run analyses and collect results grouped by declaration
        grouped = defaultdict(list)

        for line in lines:
            try:
                status = line.retrieve_deforestation_status()

                line._apply_deforestation_status(status)

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
        declarations = lines.mapped('declaration_id')
        if declarations:
            declarations._set_stage_from_xmlid('planetio.eudr_stage_validated')
        return True

    # ---------- Alerts helpers ----------
    def _sync_alert_records_from_status(self, status):
        if not isinstance(status, dict):
            return

        alerts_payload = self._extract_alerts_from_payload(status)
        if alerts_payload is None:
            return

        self.alert_ids.unlink()
        if not alerts_payload:
            return

        provider = None
        if isinstance(status.get('meta'), dict):
            provider = status['meta'].get('provider')

        Alert = self.env['eudr.declaration.line.alert']
        create_vals = []
        for alert in alerts_payload:
            vals = self._prepare_alert_vals(alert, provider)
            if vals:
                create_vals.append(vals)

        if create_vals:
            Alert.create(create_vals)

    def _extract_alerts_from_payload(self, payload):
        def _search(node):
            if isinstance(node, dict):
                alerts = node.get('alerts')
                if isinstance(alerts, list):
                    if alerts and all(isinstance(item, dict) for item in alerts):
                        return alerts
                    if not alerts:
                        return []
                for value in node.values():
                    found = _search(value)
                    if found is not None:
                        return found
            elif isinstance(node, list):
                for item in node:
                    found = _search(item)
                    if found is not None:
                        return found
            return None

        result = _search(payload)
        if isinstance(result, list):
            return result
        summary_alert = self._build_summary_alert_from_payload(payload)
        if summary_alert:
            return [summary_alert]
        return None

    def _build_summary_alert_from_payload(self, payload):
        if not isinstance(payload, dict):
            return None

        meta = payload.get('meta') if isinstance(payload.get('meta'), dict) else {}
        metrics = payload.get('metrics') if isinstance(payload.get('metrics'), dict) else {}
        details = payload.get('details') if isinstance(payload.get('details'), dict) else {}

        props_candidates = []
        if isinstance(details, dict):
            for key in (
                'externalProperties',
                'properties',
                'props',
                'data',
                'attributes',
            ):
                candidate = details.get(key)
                if isinstance(candidate, dict):
                    props_candidates.append(candidate)

        for key in ('properties', 'props', 'data', 'attributes'):
            candidate = payload.get(key)
            if isinstance(candidate, dict):
                props_candidates.append(candidate)

        props_candidates.append(payload)

        props = {}
        for candidate in props_candidates:
            if isinstance(candidate, dict) and candidate:
                props = candidate
                break

        def _pick(*keys, source=None):
            src = source if isinstance(source, dict) else props
            for key in keys:
                if isinstance(src, dict) and src.get(key) not in (None, ''):
                    return src.get(key)
            return None

        risk = _pick('risk_level_label', 'risk_level', 'risk', source=meta) or _pick(
            'risk_level_label', 'risk_level', 'risk'
        )
        if risk not in (None, ''):
            risk = tools.ustr(risk).strip()
        else:
            risk = ''

        confidence = _pick('confidence', source=meta) or _pick('confidence')
        if confidence not in (None, ''):
            confidence = tools.ustr(confidence)

        last_alert = (
            _pick('last_alert_date', 'last_alert', source=meta)
            or _pick('last_alert_date', 'last_alert')
        )
        if last_alert not in (None, ''):
            last_alert = tools.ustr(last_alert)

        period = _pick('period', 'date_range', source=meta) or _pick('period', 'date_range')
        if period not in (None, ''):
            period = tools.ustr(period)

        notes = _pick('notes', source=meta) or _pick('notes')
        if notes not in (None, ''):
            notes = tools.ustr(notes)

        primary_drivers = _pick('primary_drivers', source=meta) or _pick('primary_drivers')

        source = _pick('source', 'provider', source=meta) or _pick('source', 'provider')
        if source not in (None, ''):
            source = tools.ustr(source)

        provider = tools.ustr(meta.get('provider')) if meta.get('provider') else None
        if not provider and props.get('provider'):
            provider = tools.ustr(props.get('provider'))
        if not provider and source:
            provider = source

        alert_count = None
        for key in (
            'alert_count',
            'alert_count_total',
            'alerts_total',
            'alert_count_30d',
            'alerts_30d',
            'alert_count_7d',
            'alerts_7d',
            'alertcount',
            'alerts',
            'alertcount30d',
        ):
            if key in metrics and metrics.get(key) not in (None, ''):
                alert_count = metrics.get(key)
                break
            if key in props and props.get(key) not in (None, ''):
                alert_count = props.get(key)
                break
        if alert_count not in (None, ''):
            coerced_count = _coerce_int(alert_count)
            alert_count = coerced_count if coerced_count is not None else alert_count

        area_val = None
        for key in (
            'area_ha_total',
            'alert_area_ha',
            'area_ha',
            'area_hectares',
            'affected_area_ha',
        ):
            if key in metrics and metrics.get(key) not in (None, ''):
                area_val = metrics.get(key)
                break
            if key in props and props.get(key) not in (None, ''):
                area_val = props.get(key)
                break
        if area_val not in (None, ''):
            coerced_area = _coerce_float(area_val)
            area_val = coerced_area if coerced_area is not None else area_val

        location = None
        for key in ('name', 'title', 'label', 'state', 'region', 'location'):
            if props.get(key) not in (None, ''):
                location = tools.ustr(props.get(key))
                break

        interesting_values = [
            risk,
            confidence,
            last_alert,
            period,
            notes,
            primary_drivers,
            source,
            alert_count,
            area_val,
            location,
        ]
        has_interesting_data = any(
            value not in (None, '', []) for value in interesting_values
        )
        if not has_interesting_data:
            return None

        summary = {}
        if location:
            summary['name'] = location
        if provider:
            summary['provider'] = provider
        if source:
            summary['source'] = source
        if risk:
            summary['risk_level'] = risk
        if confidence not in (None, ''):
            summary['confidence'] = confidence
        if alert_count not in (None, ''):
            summary['alert_count'] = alert_count
        if area_val not in (None, ''):
            summary['alert_area_ha'] = area_val
        if last_alert:
            summary['last_alert_date'] = last_alert
        if period:
            summary['period'] = period
        if notes:
            summary['notes'] = notes
        if primary_drivers not in (None, ''):
            summary['primary_drivers'] = primary_drivers

        identifier = (
            props.get('id')
            or props.get('identifier')
            or props.get('glad_id')
            or props.get('gladId')
            or (period and f"period:{period}")
            or (last_alert and f"last:{last_alert}")
            or (location and location.lower())
            or provider
        )
        if identifier not in (None, ''):
            summary['id'] = tools.ustr(identifier)

        return summary

    def _prepare_alert_vals(self, alert, provider):
        if not isinstance(alert, dict):
            return None

        provider_name = alert.get('provider') or alert.get('source') or provider or 'gfw'

        identifier = None
        for key in ('id', 'alert_id', 'alertId', 'glad_id', 'gladId', 'identifier'):
            if alert.get(key):
                identifier = tools.ustr(alert.get(key))
                break

        name = None
        for key in ('name', 'title', 'label'):
            if alert.get(key):
                name = tools.ustr(alert.get(key))
                break
        if not name and identifier:
            name = identifier

        alert_date, alert_date_raw = self._normalize_alert_date(alert)

        area_val = None
        for key in ('area_ha', 'areaHa', 'alert_area_ha', 'areaHaTotal'):
            if key in alert:
                area_val = _coerce_float(alert.get(key))
                if area_val is not None:
                    break

        lat = None
        lon = None
        for key in ('latitude', 'lat'):
            if alert.get(key) not in (None, ''):
                lat = _coerce_float(alert.get(key))
                if lat is not None:
                    break
        for key in ('longitude', 'lon', 'lng'):
            if alert.get(key) not in (None, ''):
                lon = _coerce_float(alert.get(key))
                if lon is not None:
                    break

        if (lat is None or lon is None) and isinstance(alert.get('coordinates'), (list, tuple)):
            coords = alert.get('coordinates')
            if len(coords) >= 2:
                lon = _coerce_float(coords[0]) if lon is None else lon
                lat = _coerce_float(coords[1]) if lat is None else lat

        if (lat is None or lon is None) and isinstance(alert.get('geometry'), dict):
            geom = alert['geometry']
            coords = geom.get('coordinates') if isinstance(geom, dict) else None
            if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                lon = _coerce_float(coords[0]) if lon is None else lon
                lat = _coerce_float(coords[1]) if lat is None else lat

        risk_level = None
        for key in ('risk_level', 'riskLevel', 'risk'):
            if alert.get(key):
                risk_level = tools.ustr(alert.get(key))
                break

        confidence = None
        for key in ('confidence', 'confidence_level', 'confidenceLevel'):
            if alert.get(key):
                confidence = tools.ustr(alert.get(key))
                break

        try:
            payload_json = json.dumps(alert, ensure_ascii=False)
        except Exception:
            payload_json = tools.ustr(alert)

        def _extract_description_candidates(container):
            if not isinstance(container, dict):
                return None
            keys = (
                'problem_description',
                'problemDescription',
                'description',
                'issue',
                'issue_description',
                'alert_description',
                'deforestation_problem',
                'deforestation_issue',
                'notes',
                'summary',
                'details',
                'message',
                'comment',
            )
            for key in keys:
                if key not in container:
                    continue
                value = container.get(key)
                if value in (None, ''):
                    continue
                if isinstance(value, (list, tuple)):
                    text = ', '.join(
                        tools.ustr(item).strip()
                        for item in value
                        if item not in (None, '')
                    ).strip(', ')
                else:
                    text = tools.ustr(value).strip()
                if text:
                    return text
            return None

        description = _extract_description_candidates(alert)
        if not description and isinstance(alert.get('details'), dict):
            description = _extract_description_candidates(alert['details'])
        if not description and isinstance(alert.get('properties'), dict):
            description = _extract_description_candidates(alert['properties'])
        if not description and isinstance(alert.get('meta'), dict):
            description = _extract_description_candidates(alert['meta'])

        vals = {
            'line_id': self.id,
            'provider': provider_name,
            'alert_identifier': identifier,
            'name': name,
            'alert_date': alert_date,
            'alert_date_raw': alert_date_raw,
            'risk_level': risk_level,
            'confidence': confidence,
            'area_ha': area_val or 0.0,
            'latitude': lat,
            'longitude': lon,
            'payload_json': payload_json,
        }

        if description:
            vals['problem_description'] = description

        # Remove keys with None to keep the record clean, but keep False/0
        vals = {key: value for key, value in vals.items() if value not in (None, '')}
        vals['line_id'] = self.id
        vals['provider'] = provider_name
        vals['area_ha'] = vals.get('area_ha', 0.0)
        vals['payload_json'] = payload_json

        if alert_date_raw and 'alert_date_raw' not in vals:
            vals['alert_date_raw'] = alert_date_raw

        if 'name' not in vals:
            fallback = alert_date_raw or identifier or provider_name
            if fallback:
                vals['name'] = tools.ustr(fallback)

        return vals

    def _normalize_alert_date(self, alert):
        candidates = []
        if isinstance(alert, dict):
            for key in (
                'alert_date',
                'alertDate',
                'date',
                'detected_on',
                'detectedOn',
                'last_alert_date',
                'lastAlertDate',
                'start_date',
                'startDate',
                'last_seen',
            ):
                if alert.get(key) not in (None, ''):
                    candidates.append(alert.get(key))
        elif alert not in (None, ''):
            candidates.append(alert)

        for candidate in candidates:
            parsed, raw = self._parse_alert_date_value(candidate)
            if raw:
                return parsed, raw
        return None, None

    def _parse_alert_date_value(self, value):
        if isinstance(value, date):
            return value, value.isoformat()
        if isinstance(value, datetime):
            return value.date(), value.isoformat()
        if isinstance(value, (int, float)):
            try:
                dt = datetime.utcfromtimestamp(float(value))
                return dt.date(), dt.date().isoformat()
            except Exception:
                return None, str(value)
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return None, None
            text = raw
            if 'T' in text:
                text = text.split('T', 1)[0]
            text = text.replace('/', '-')
            match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", text)
            if match:
                try:
                    return date(
                        int(match.group(1)),
                        int(match.group(2)),
                        int(match.group(3)),
                    ), raw
                except ValueError:
                    return None, raw
            match = re.match(r"^(\d{8})", re.sub(r"[^0-9]", "", text))
            if match:
                token = match.group(1)
                try:
                    return date(
                        int(token[0:4]),
                        int(token[4:6]),
                        int(token[6:8]),
                    ), raw
                except ValueError:
                    return None, raw
            return None, raw
        return None, None


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

    def action_create_deforestation_geojson(self):
        from ..services.eudr_adapter_odoo import (
            attach_deforestation_geojson,
            build_deforestation_geojson,
        )

        for decl in self:
            geojson_dict = build_deforestation_geojson(decl)
            attachment = attach_deforestation_geojson(decl, geojson_dict)
            decl.message_post(
                body=_(
                    "Deforestation GeoJSON created and saved as <b>%s</b>."
                )
                % attachment.name
            )
        return True
