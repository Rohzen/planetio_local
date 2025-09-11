# -*- coding: utf-8 -*-
import logging
from odoo import _
from odoo.exceptions import UserError
from .gfw_client import GFWClient

_logger = logging.getLogger(__name__)

def _base_url(env):
    ICP = env['ir.config_parameter'].sudo()
    return (ICP.get_param('planetio.gfw_base_url') or 'https://api.globalforestwatch.org').rstrip('/')

def gfw_request(env, method, endpoint, *, params=None, json=None, timeout=40):
    client = GFWClient(env)
    url = endpoint if endpoint.startswith('http') else f"{_base_url(env)}{endpoint if endpoint.startswith('/') else '/'+endpoint}"
    resp = client.request(method, url, params=(params or {}), json=json, timeout=timeout)
    try:
        resp.raise_for_status()
    except Exception:
        snip = (resp.text or '')[:600]
        _logger.warning("GFW %s %s -> HTTP %s\nResp: %s", method, url, resp.status_code, snip)
        raise
    return resp

def gfw_get_alerts(env, *, endpoint='/v1/glad-alerts', params=None, timeout=40):
    resp = gfw_request(env, 'GET', endpoint, params=params or {}, timeout=timeout)
    try:
        return resp.json()
    except Exception:
        raise UserError(_("Risposta GFW non in JSON (endpoint: %s).") % endpoint)

def gfw_post_analysis(env, *, endpoint, payload, timeout=60):
    resp = gfw_request(env, 'POST', endpoint, json=payload, timeout=timeout)
    try:
        return resp.json()
    except Exception:
        raise UserError(_("Risposta GFW non in JSON (endpoint: %s).") % endpoint)
