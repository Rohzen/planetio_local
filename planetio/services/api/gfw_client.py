#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import logging
from datetime import datetime, timedelta, timezone

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from odoo import _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def _to_dt(val):
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    try:
        return datetime.fromisoformat(str(val).replace('Z', '+00:00'))
    except Exception:
        return None


class GFWClient:
    def __init__(self, env):
        self.env = env
        self.ICP = env['ir.config_parameter'].sudo()

        self.session = requests.Session()
        retry = Retry(total=3, backoff_factor=0.8,
                      status_forcelist=[429, 502, 503, 504],
                      allowed_methods=frozenset(['GET', 'POST', 'PUT', 'DELETE']))
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        self.session.headers.update({'User-Agent': 'planetio/odoo14 (+GFWClient)'})

    def ensure_api_key(self):
        mode = (self.ICP.get_param('planetio.gfw_auth_mode') or 'api_key').strip()
        if mode == 'api_key':
            key = (self.ICP.get_param('planetio.gfw_api_key') or '').strip()
            if not key:
                raise UserError(_('Parametro planetio.gfw_api_key mancante.'))
            return key

        key = (self.ICP.get_param('planetio.gfw_api_key') or '').strip()
        exp = _to_dt(self.ICP.get_param('planetio.gfw_key_expires_at'))
        now = datetime.now(timezone.utc)
        if (not key) or (not exp) or (exp - now <= timedelta(minutes=5)):
            key, exp = self._login_and_store()
        return key

    def request(self, method, url, timeout=30, **kwargs):
        key = self.ensure_api_key()
        headers = kwargs.pop('headers', {}) or {}
        auth_header_mode = (self.ICP.get_param('planetio.gfw_auth_header') or 'x-api-key').strip()
        if auth_header_mode == 'authorization_bearer':
            headers['Authorization'] = f'Bearer {key}'
        else:
            headers['x-api-key'] = key

        resp = self.session.request(method.upper(), url, headers=headers, timeout=timeout, **kwargs)
        if resp.status_code in (401, 403) and (self.ICP.get_param('planetio.gfw_auth_mode') or 'api_key') == 'email_password':
            _logger.info('GFW 401/403: provo a rinnovare la chiave…')
            self._login_and_store()
            key2 = (self.ICP.get_param('planetio.gfw_api_key') or '').strip()
            if auth_header_mode == 'authorization_bearer':
                headers['Authorization'] = f'Bearer {key2}'
            else:
                headers['x-api-key'] = key2
            resp = self.session.request(method.upper(), url, headers=headers, timeout=timeout, **kwargs)
        return resp

    def _login_and_store(self):
        email = (self.ICP.get_param('planetio.gfw_email') or '').strip()
        password = (self.ICP.get_param('planetio.gfw_password') or '').strip()
        auth_url = (self.ICP.get_param('planetio.gfw_auth_url') or '').strip()
        method = (self.ICP.get_param('planetio.gfw_auth_method') or 'POST').strip().upper()
        token_field = (self.ICP.get_param('planetio.gfw_token_field') or 'apiKey').strip()
        expires_at_field = (self.ICP.get_param('planetio.gfw_expires_at_field') or '').strip()
        expires_in_field = (self.ICP.get_param('planetio.gfw_expires_in_field') or '').strip()

        if not email or not password or not auth_url:
            raise UserError(_('Configurazione GFW incompleta: email/password/auth_url obbligatori in modalità Email + Password.'))

        payload = {'email': email, 'password': password}
        headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}

        if method == 'GET':
            resp = self.session.get(auth_url, params=payload, headers=headers, timeout=30)
        else:
            resp = self.session.post(auth_url, data=json.dumps(payload), headers=headers, timeout=30)

        if resp.status_code not in (200, 201):
            raise UserError(_('Login GFW fallito (HTTP %s): %s') % (resp.status_code, (resp.text or '')[:400]))

        try:
            data = resp.json()
        except Exception:
            raise UserError(_('Risposta login non JSON.'))

        token = data.get(token_field) or data.get('access_token') or data.get('api_key')
        if not token:
            raise UserError(_('Token non trovato nella risposta: atteso "%s" (o access_token/api_key).') % token_field)

        exp_dt = None
        if expires_at_field and data.get(expires_at_field):
            exp_dt = _to_dt(data.get(expires_at_field))
        elif expires_in_field and data.get(expires_in_field):
            try:
                secs = int(data.get(expires_in_field))
                exp_dt = datetime.now(timezone.utc) + timedelta(seconds=max(60, secs))
            except Exception:
                exp_dt = None
        if not exp_dt:
            exp_dt = datetime.now(timezone.utc) + timedelta(hours=23)

        self.ICP.set_param('planetio.gfw_api_key', token)
        self.ICP.set_param('planetio.gfw_key_expires_at', exp_dt.isoformat())
        _logger.info('GFW token aggiornato; scadenza: %s', exp_dt.isoformat())
        return token, exp_dt
