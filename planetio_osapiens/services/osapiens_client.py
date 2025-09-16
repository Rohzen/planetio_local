# -*- coding: utf-8 -*-
import json
import time
import logging
import requests

DEFAULT_TIMEOUT = 60
MAX_RETRIES = 3
BACKOFF_SEC = 2.0

_logger = logging.getLogger(__name__)

class OsapiensClient:
    """
    Client generico per oSapiens Supplier Portal / EUDR.
    Gli endpoint sono segnaposto e vanno sostituiti con quelli ufficiali.
    Autenticazione: adeguare gli header in base alle specifiche reali.
    """

    def __init__(self, env):
        self.env = env
        icp = env['ir.config_parameter'].sudo()
        self.base_url = (icp.get_param('osapiens.base_url') or '').rstrip('/')
        self.account_id = icp.get_param('osapiens.account_id') or ''
        self.api_token = icp.get_param('osapiens.api_token') or ''
        self.timeout = int(icp.get_param('osapiens.timeout') or DEFAULT_TIMEOUT)
        self.verify_ssl = icp.get_param('osapiens.verify_ssl')
        if isinstance(self.verify_ssl, str):
            self.verify_ssl = self.verify_ssl.lower() in ('1', 'true', 'yes')
        if not self.base_url or not self.account_id or not self.api_token:
            raise ValueError("Configurazione oSapiens incompleta: base_url/account_id/api_token richiesti.")

    def _auth_headers(self):
        return {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-Account-Id': self.account_id,
            'Authorization': f'Bearer {self.api_token}',
        }

    def _log_ir(self, level, name, message):
        try:
            self.env['ir.logging'].sudo().create({
                'name': (name or '')[:250],
                'type': 'server',
                'dbuuid': self.env.cr.dbname,
                'level': (level or 'info').lower(),
                'message': (message or '')[:10000],
                'path': 'osapiens_client',
                'func': 'request',
                'line': 0,
            })
        except Exception:
            _logger.exception("Errore scrittura ir.logging")

    def _request(self, method, path, payload=None, params=None, files=None):
        url = f"{self.base_url}{path}"
        headers = self._auth_headers()
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                if files:
                    resp = requests.request(method, url, headers=headers, data=payload, files=files,
                                            timeout=self.timeout, verify=self.verify_ssl)
                else:
                    resp = requests.request(method, url, headers=headers, json=payload, params=params,
                                            timeout=self.timeout, verify=self.verify_ssl)
                if 200 <= resp.status_code < 300:
                    ct = resp.headers.get('Content-Type', '')
                    if ct.startswith('application/json'):
                        return resp.json()
                    return resp.text or {}
                else:
                    self._log_ir('ERROR', f"HTTP {resp.status_code} {method} {url}", resp.text)
                    if resp.status_code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
                        time.sleep(BACKOFF_SEC * attempt)
                        continue
                    resp.raise_for_status()
            except requests.RequestException as e:
                self._log_ir('ERROR', f"Request error {method} {url}", str(e))
                if attempt < MAX_RETRIES:
                    time.sleep(BACKOFF_SEC * attempt)
                    continue
                raise
        return {}

    # ========== Esempi di funzioni (path segnaposto) ==========

    def list_rfi_requests(self, status='open', limit=50, offset=0):
        path = "/api/v1/eudr/requests"
        params = {'status': status, 'limit': limit, 'offset': offset}
        return self._request('GET', path, params=params)

    def submit_rfi_answers(self, request_id, answers, attachments=None):
        path = f"/api/v1/eudr/requests/{request_id}/answers"
        payload = {'answers': answers or {}}
        if attachments:
            payload['attachments'] = attachments
        return self._request('POST', path, payload=payload)

    def create_or_update_plot(self, plot_id, geojson, metadata=None):
        path = f"/api/v1/eudr/plots/{plot_id}"
        payload = {'geometry': geojson}
        if metadata:
            payload['metadata'] = metadata
        return self._request('PUT', path, payload=payload)

    def create_lot(self, product_sku, harvest_year, plot_ids, extra=None):
        path = "/api/v1/eudr/lots"
        payload = {
            'product_sku': product_sku,
            'harvest_year': harvest_year,
            'plots': plot_ids,
        }
        if extra:
            payload.update(extra)
        return self._request('POST', path, payload=payload)

    def attach_dds_reference(self, entity_type, entity_id, dds_reference, verification_code=None):
        path = f"/api/v1/eudr/{entity_type}s/{entity_id}/dds"
        payload = {'dds_reference': dds_reference}
        if verification_code:
            payload['verification_code'] = verification_code
        return self._request('POST', path, payload=payload)

    def get_dds_status(self, dds_reference):
        path = f"/api/v1/eudr/dds/{dds_reference}/status"
        return self._request('GET', path)

    def upload_document(self, entity_type, entity_id, filename, content_b64, mimetype='application/pdf'):
        path = f"/api/v1/eudr/{entity_type}s/{entity_id}/documents"
        payload = {
            'filename': filename,
            'mimetype': mimetype,
            'content_base64': content_b64,
        }
        return self._request('POST', path, payload=payload)