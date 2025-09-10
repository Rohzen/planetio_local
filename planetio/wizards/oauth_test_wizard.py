# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import json
import requests

class OAuthTestWizard(models.TransientModel):
    _name = "planetio.oauth.test.wizard"
    _description = "Test OAuth client-credentials and save settings"

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
