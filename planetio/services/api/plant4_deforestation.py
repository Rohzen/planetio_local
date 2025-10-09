from odoo import models, _
from odoo.exceptions import UserError
from odoo.tools import ustr

import json
import uuid
import requests


class DeforestationProviderPlant4(models.AbstractModel):
    _name = 'deforestation.provider.plant4'
    _inherit = 'deforestation.provider.base'
    _description = 'Deforestation Provider - Plant-for-the-Planet'

    _COUNT_KEYS = [
        'alert_count',
        'alerts_count',
        'alertsTotal',
        'alerts',
        'deforestation_alerts',
        'deforestationAlerts',
        'alertCount',
        'alert_count_total',
    ]
    _AREA_KEYS = [
        'area_ha',
        'areaHa',
        'area_hectares',
        'deforestation_area',
        'deforestation_area_ha',
        'deforestationArea',
        'alert_area_ha',
    ]
    _RISK_KEYS = [
        'risk',
        'risk_level',
        'riskLevel',
        'risk_category',
        'riskCategory',
        'deforestation_detected',
        'deforestation',
        'has_deforestation',
        'status',
    ]
    _CONFIDENCE_KEYS = ['confidence', 'confidence_level', 'confidenceLevel']
    _LAST_ALERT_KEYS = ['last_alert_date', 'lastAlertDate', 'last_alert', 'lastAlert']
    _PERIOD_KEYS = ['period', 'date_range', 'dateRange']

    def _get_config(self):
        icp = self.env['ir.config_parameter'].sudo()
        api_key = (icp.get_param('deforestation.plant4.api_key') or '').strip()
        base_url = (icp.get_param('deforestation.plant4.base_url') or 'https://farm.tracer.eco').strip()
        if base_url.endswith('/'):
            base_url = base_url[:-1]
        if not base_url:
            base_url = 'https://farm.tracer.eco'
        return api_key, base_url

    def check_prerequisites(self):
        api_key, base_url = self._get_config()
        if not api_key:
            raise UserError(_("API key Plant-for-the-Planet mancante. Impostala nelle configurazioni."))
        if not base_url:
            raise UserError(_("URL base Plant-for-the-Planet mancante."))

    # ------------------------------------------------------------------
    def analyze_line(self, line):
        api_key, base_url = self._get_config()
        geometry = self._extract_geometry(line)
        if not geometry:
            raise UserError(_("Geometria mancante sulla riga %s") % (getattr(line, 'display_name', line.id)))

        uid = self._build_uid(line)
        payload = self._build_payload(line, geometry, uid)
        url = f"{base_url}/api/farm-data"
        headers = {
            'x-api-key': api_key,
            'Content-Type': 'application/json',
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=120)
        except requests.exceptions.RequestException as ex:
            raise UserError(_("Connessione a Plant-for-the-Planet non riuscita: %s") % str(ex))

        data = None
        if response.status_code == 409:
            data = self._fetch_existing(base_url, headers, uid)
        elif response.status_code == 401:
            raise UserError(_("API key Plant-for-the-Planet non valida o scaduta."))
        elif response.status_code == 404:
            raise UserError(_("Endpoint Plant-for-the-Planet non trovato: %s") % url)
        elif response.status_code >= 500:
            raise UserError(_("Plant-for-the-Planet ha risposto con errore temporaneo (%s).") % response.status_code)
        elif response.status_code >= 400:
            raise UserError(self._build_http_error(response))
        else:
            data = self._json_or_error(response)

        if not isinstance(data, (dict, list)):
            raise UserError(_("Risposta Plant-for-the-Planet inattesa."))

        properties = self._extract_first_feature_properties(data)
        block, block_path = self._find_deforestation_block(data)
        if not block and properties:
            block, block_path = self._find_deforestation_block(properties)

        alerts = self._extract_alerts(block, properties)
        metrics = self._build_metrics([block, properties, data], alerts)
        meta = self._build_meta([block, properties, data], uid, metrics)
        if block_path:
            meta['deforestation_path'] = block_path

        message = _("Plant-for-the-Planet: %(cnt)s allerta/e") % {
            'cnt': metrics.get('alert_count', 0)
        }

        details = {'deforestation': block or {}, 'properties': properties or {}, 'payload': payload}
        try:
            details['response'] = data if isinstance(data, (dict, list)) else json.loads(json.dumps(data))
        except Exception:
            pass

        result = {
            'message': message,
            'alerts': alerts,
            'metrics': metrics,
            'meta': meta,
            'details': details,
        }
        return result

    # ------------------------------------------------------------------
    def _extract_geometry(self, line):
        geom = None
        if hasattr(line, '_line_geometry'):
            try:
                geom = line._line_geometry()
            except Exception:
                geom = None
        if not geom:
            raw = getattr(line, 'geojson', None)
            if raw:
                try:
                    geom = json.loads(raw) if isinstance(raw, str) else raw
                except Exception:
                    geom = None
        return geom if isinstance(geom, dict) else None

    def _build_uid(self, line):
        base = f"eudr-{getattr(line, 'id', 'line')}"
        return f"{base}-{uuid.uuid4().hex[:8]}"

    def _build_payload(self, line, geometry, uid):
        declaration = getattr(line, 'declaration_id', None)
        hs_record = getattr(declaration, 'hs_code_id', None)
        commodity_code = getattr(hs_record, 'code', None)
        commodity_label = getattr(hs_record, 'commodity', None)
        commodity = commodity_label or commodity_code or 'coffee'
        commodity_values = []
        if commodity_label and commodity_code:
            commodity_values.extend([ustr(commodity_code), ustr(commodity_label)])
        elif commodity:
            commodity_values.append(ustr(commodity))
        if not commodity_values:
            commodity_values = ['coffee']

        feature = {
            'type': 'Feature',
            'properties': {
                'uid': uid,
                'commodity': commodity_values,
                'source': 'planetio',
                'line_id': getattr(line, 'id', None),
                'line_name': ustr(getattr(line, 'display_name', '')), 
            },
            'geometry': geometry,
        }

        return {
            'geoJSON': {
                'type': 'FeatureCollection',
                'features': [feature],
            }
        }

    def _fetch_existing(self, base_url, headers, uid):
        try:
            response = requests.get(f"{base_url}/api/farm-data", headers=headers, params={'uid': uid}, timeout=60)
        except requests.exceptions.RequestException as ex:
            raise UserError(_("Impossibile recuperare l'analisi Plant-for-the-Planet esistente: %s") % str(ex))

        if response.status_code == 404:
            raise UserError(_("Analisi Plant-for-the-Planet non trovata per UID %s") % uid)
        if response.status_code >= 400:
            raise UserError(self._build_http_error(response))
        return self._json_or_error(response)

    def _json_or_error(self, response):
        try:
            return response.json()
        except ValueError:
            snippet = (response.text or '')[:300]
            raise UserError(_("Risposta Plant-for-the-Planet non è JSON valido: %s") % snippet)

    def _build_http_error(self, response):
        detail = None
        try:
            payload = response.json()
            if isinstance(payload, dict):
                detail = payload.get('detail') or payload.get('message')
        except ValueError:
            detail = None
        detail = detail or (response.text or '').strip()
        return _(
            "Richiesta Plant-for-the-Planet rifiutata (%(code)s): %(detail)s"
        ) % {'code': response.status_code, 'detail': detail[:300] if detail else ''}

    def _extract_first_feature_properties(self, data):
        candidates = []
        if isinstance(data, dict):
            if isinstance(data.get('features'), list) and data['features']:
                first = data['features'][0]
                if isinstance(first, dict):
                    candidates.append(first.get('properties'))
            geojson = data.get('geoJSON')
            if isinstance(geojson, dict):
                if isinstance(geojson.get('features'), list) and geojson['features']:
                    first = geojson['features'][0]
                    if isinstance(first, dict):
                        candidates.append(first.get('properties'))
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate:
                return candidate
        return {}

    def _find_deforestation_block(self, payload):
        queue = [(payload, '')]
        visited = set()
        while queue:
            node, path = queue.pop(0)
            if id(node) in visited:
                continue
            visited.add(id(node))
            if isinstance(node, dict):
                for key, value in node.items():
                    new_path = f"{path}.{key}" if path else key
                    if isinstance(key, str):
                        key_lower = key.lower()
                        if 'deforest' in key_lower or 'forest_loss' in key_lower:
                            if isinstance(value, dict):
                                return value, new_path
                    if isinstance(value, (dict, list)):
                        queue.append((value, new_path))
            elif isinstance(node, list):
                for idx, value in enumerate(node):
                    new_path = f"{path}[{idx}]" if path else f"[{idx}]"
                    if isinstance(value, (dict, list)):
                        queue.append((value, new_path))
        return {}, None

    def _extract_alerts(self, *sources):
        for source in sources:
            if isinstance(source, dict):
                for key, value in source.items():
                    if isinstance(key, str) and 'alert' in key.lower() and isinstance(value, list):
                        if not value or all(isinstance(item, dict) for item in value):
                            return value
        return []

    def _build_metrics(self, sources, alerts):
        count = None
        area = None
        for source in sources:
            if not isinstance(source, dict):
                continue
            if count is None:
                for key in self._COUNT_KEYS:
                    if source.get(key) not in (None, ''):
                        value = self._coerce_int(source.get(key))
                        if value is not None:
                            count = value
                            break
            if area is None:
                for key in self._AREA_KEYS:
                    if source.get(key) not in (None, ''):
                        value = self._coerce_float(source.get(key))
                        if value is not None:
                            area = value
                            break
        if count is None:
            count = len(alerts)
        return {
            'alert_count': count or 0,
            'area_ha_total': area or 0.0,
        }

    def _build_meta(self, sources, uid, metrics):
        meta = {
            'provider': 'plant4',
            'uid': uid,
        }
        risk_flag = metrics.get('alert_count', 0) > 0
        for source in sources:
            if not isinstance(source, dict):
                continue
            for key in self._RISK_KEYS:
                if source.get(key) in (None, ''):
                    continue
                value = source.get(key)
                if isinstance(value, bool):
                    risk_flag = risk_flag or value
                elif isinstance(value, (int, float)):
                    risk_flag = risk_flag or value > 0
                else:
                    text = ustr(value).strip().lower()
                    if text in ('true', 'yes', 'detected', 'high', 'medium', 'alert', 'at risk'):
                        risk_flag = True
                if 'risk_level' not in meta and isinstance(value, str):
                    meta['risk_level'] = ustr(value)
            for key in self._CONFIDENCE_KEYS:
                if source.get(key) not in (None, '') and 'confidence' not in meta:
                    meta['confidence'] = ustr(source.get(key))
            for key in self._LAST_ALERT_KEYS:
                if source.get(key) not in (None, '') and 'last_alert_date' not in meta:
                    meta['last_alert_date'] = ustr(source.get(key))
            for key in self._PERIOD_KEYS:
                if source.get(key) not in (None, '') and 'period' not in meta:
                    meta['period'] = ustr(source.get(key))
            if source.get('commodity') and 'commodity' not in meta:
                meta['commodity'] = source.get('commodity')
        meta['risk_flag'] = risk_flag
        return meta

    @staticmethod
    def _coerce_int(value):
        try:
            if isinstance(value, bool):
                return int(value)
            if isinstance(value, (int, float)):
                return int(round(float(value)))
            text = ustr(value).strip()
            if not text:
                return None
            return int(round(float(text)))
        except Exception:
            return None

    @staticmethod
    def _coerce_float(value):
        try:
            if isinstance(value, bool):
                return float(int(value))
            if isinstance(value, (int, float)):
                return float(value)
            text = ustr(value).strip()
            if not text:
                return None
            return float(text)
        except Exception:
            return None
