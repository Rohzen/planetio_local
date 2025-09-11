# -*- coding: utf-8 -*-
import time
import logging
import requests
from typing import Optional, Dict, Any
from odoo import models

_logger = logging.getLogger(__name__)

class OAuthTokenManager(models.AbstractModel):
    _name = "planetio.oauth.manager"
    _description = "OAuth2 client-credentials token manager"

    def _param(self, key: str, default: Any = None) -> Any:
        return self.env["ir.config_parameter"].sudo().get_param(key, default)

    def _set_param(self, key: str, value: Any) -> None:
        self.env["ir.config_parameter"].sudo().set_param(key, value)

    def get_token(self, key_prefix: str, token_url: str, client_id: str, client_secret: str, scope: Optional[str] = None) -> str:
        """Return a valid access token for the given key_prefix, minting as needed.

        Stores token and expiry in ir.config_parameter keys:
          {key_prefix}.access_token
          {key_prefix}.token_expiry_epoch
        """
        now = int(time.time())
        tok_key = f"{key_prefix}.access_token"
        exp_key = f"{key_prefix}.token_expiry_epoch"
        token = self._param(tok_key)
        exp = int(self._param(exp_key, 0) or 0)
        # small safety margin of 60s
        if token and exp - 60 > now:
            return token

        data = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }
        if scope:
            data["scope"] = scope
        resp = requests.post(token_url, data=data, timeout=60)
        if resp.status_code != 200:
            raise RuntimeError(f"OAuth token error {resp.status_code}: {resp.text[:200]}")
        obj = resp.json() or {}
        token = obj.get("access_token")
        ttl = int(obj.get("expires_in") or 3600)
        if not token:
            raise RuntimeError("OAuth token response missing 'access_token'")
        self._set_param(tok_key, token)
        self._set_param(exp_key, str(now + ttl))
        _logger.info("Minted new OAuth token for %s (ttl=%ss)", key_prefix, ttl)
        return token
