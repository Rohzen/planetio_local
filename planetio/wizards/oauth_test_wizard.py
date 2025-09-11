import time
# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import json
import requests

class OAuthTestWizard(models.TransientModel):
    _name = "planetio.oauth.test.wizard"
    _description = "Test OAuth client-credentials and save settings"
    # --- GFW API Key Section ---
    gfw_email = fields.Char(string="GFW Email")
    gfw_password = fields.Char(string="GFW Password", password=True)
    gfw_org = fields.Char(string="Organization")
    gfw_alias = fields.Char(string="API Key Alias", default="planetio-dev")
    gfw_domains = fields.Char(string="Allowed Domains (JSON)", help='E.g. ["localhost"]')
    gfw_origin = fields.Char(string="Origin header", help="Must match a domain in the allowlist, e.g. http://localhost")
    api_key_preview = fields.Char(string="API Key (preview)", readonly=True)


    provider = fields.Selection([('gfw','Global Forest Watch')], default='gfw', required=True)
    token_url = fields.Char(required=True, string="Token URL")
    client_id = fields.Char(required=True, string="Client ID")
    client_secret = fields.Char(required=True, string="Client Secret")
    scope = fields.Char(string="Scope (opzionale)")
    test_url = fields.Char(string="Test URL (opzionale)",
                           help="Endpoint da chiamare con Authorization: Bearer <token> per verificare l'accesso.")
    save_params = fields.Boolean(string="Salva impostazioni nei Parametri di Sistema", default=True)

    token_preview = fields.Char(string="Token (preview)", readonly=True)
    result_message = fields.Text(string="Esito", readonly=True)

    def action_test_and_save(self):
        self.ensure_one()
        key_prefix = f"planetio.{self.provider}_oauth"
        # usa il token manager per ottenere un token
        mgr = self.env['planetio.oauth.manager']
        try:
            token = mgr.get_token(
                key_prefix=key_prefix,
                token_url=self.token_url,
                client_id=self.client_id,
                client_secret=self.client_secret,
                scope=self.scope or None,
            )
        except Exception as e:
            raise UserError(_("Errore ottenendo il token: %s") % e)

        # Test opzionale: chiamata GET su test_url se presente
        msg = _("Token ottenuto con successo.")
        if self.test_url:
            try:
                resp = requests.get(self.test_url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
                msg += _(" Test URL: codice %s.") % resp.status_code
            except Exception as e:
                msg += _(" Test URL fallito: %s") % e

        # salva i parametri se richiesto
        if self.save_params:
            ICP = self.env['ir.config_parameter'].sudo()
            # imposta modalità oauth per gfw
            if self.provider == 'gfw':
                ICP.set_param("planetio.gfw_auth_mode", "oauth")
                ICP.set_param("planetio.gfw_oauth_token_url", self.token_url)
                ICP.set_param("planetio.gfw_oauth_client_id", self.client_id)
                ICP.set_param("planetio.gfw_oauth_client_secret", self.client_secret)
                if self.scope:
                    ICP.set_param("planetio.gfw_oauth_scope", self.scope)

        # Aggiorna i campi del wizard per feedback
        self.write({
            "token_preview": (token[:6] + "..." + token[-6:]) if token else "",
            "result_message": msg,
        })

        # Riapri il wizard per mostrare i risultati
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }


    def action_get_api_key(self):
        self.ensure_one()
        BASE = "https://data-api.globalforestwatch.org"
        email = (self.gfw_email or "").strip()
        pw = (self.gfw_password or "").strip()
        alias = (self.gfw_alias or "planetio-dev").strip()
        org = (self.gfw_org or "").strip()
        domains_txt = (self.gfw_domains or "").strip()
        try:
            domains = json.loads(domains_txt) if domains_txt else None
            if domains is not None and not isinstance(domains, list):
                raise ValueError("domains must be a JSON array")
        except Exception as e:
            raise UserError(_("Domini non validi (JSON): %s") % e)

        # 1) token
        try:
            resp = requests.post(f"{BASE}/auth/token",
                                 headers={"Accept":"application/json","Content-Type":"application/x-www-form-urlencoded"},
                                 data={"username": email, "password": pw},
                                 timeout=30)
            if resp.status_code >= 400:
                raise UserError(_("Token HTTP %(c)s: %(b)s") % {'c': resp.status_code, 'b': (resp.text or '')[:400]})
            token = (resp.json().get("data") or {}).get("access_token")
            if not token:
                raise UserError(_("access_token mancante nella risposta token"))
        except Exception as e:
            raise UserError(_("Errore richiesta token: %s") % e)

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        # 2) create apikey
        payload = {"alias": alias, "email": email, "organization": org}
        if domains is not None:
            payload["domains"] = domains
        resp2 = requests.post(f"{BASE}/auth/apikey", headers=headers, json=payload, timeout=30)
        if resp2.status_code in (200, 201):
            data = resp2.json().get("data") or []
            api_key = data and data[0].get("api_key")
        elif resp2.status_code == 409:
            # list and find alias
            resp3 = requests.get(f"{BASE}/auth/apikeys", headers={"Authorization": f"Bearer {token}"}, timeout=30)
            if resp3.status_code >= 400:
                raise UserError(_("List apikey HTTP %(c)s: %(b)s") % {'c': resp3.status_code, 'b': (resp3.text or '')[:400]})
            items = resp3.json().get("data") or []
            api_key = None
            for it in items:
                if (it.get("alias") or "").strip().lower() == alias.lower():
                    api_key = it.get("api_key")
                    break
            if not api_key:
                # create with unique alias and domains if provided
                payload["alias"] = f"{alias}-{int(time.time())}"
                resp4 = requests.post(f"{BASE}/auth/apikey", headers=headers, json=payload, timeout=30)
                if resp4.status_code >= 400:
                    raise UserError(_("Create unique apikey HTTP %(c)s: %(b)s") % {'c': resp4.status_code, 'b': (resp4.text or '')[:400]})
                data = resp4.json().get("data") or []
                api_key = data and data[0].get("api_key")
        else:
            raise UserError(_("Create apikey HTTP %(c)s: %(b)s") % {'c': resp2.status_code, 'b': (resp2.text or '')[:400]})

        if not api_key:
            raise UserError(_("API key non ottenuta"))

        # Save params
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('planetio.gfw_api_key', api_key)
        if self.gfw_origin:
            ICP.set_param('planetio.gfw_api_origin', self.gfw_origin)
        if self.gfw_email:
            ICP.set_param('planetio.gfw_email', self.gfw_email)
        if self.gfw_org:
            ICP.set_param('planetio.gfw_org', self.gfw_org)
        if self.gfw_alias:
            ICP.set_param('planetio.gfw_apikey_alias', self.gfw_alias)
        if self.gfw_domains:
            ICP.set_param('planetio.gfw_domains', self.gfw_domains)

        self.write({'api_key_preview': (api_key[:6] + '...' + api_key[-6:])})
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }
