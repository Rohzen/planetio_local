import json
from urllib import request, error
from odoo import models

class AiIntentEngineLLM(models.AbstractModel):
    _inherit = 'ai.intent.engine'

    # ---- util ----
    def _allowed_models(self):
        IrModel = self.env['ir.model'].sudo()
        deny_prefix = ('ir.', 'base.', 'portal.', 'bus.', 'digest.', 'mail.channel.member')
        deny_exact = {
            'res.users', 'res.partner.bank', 'res.config.settings',
            'account.bank.statement.line', 'account.move.line'
        }
        allowed = []
        for m in IrModel.search([]):
            name = m.model
            if not name or name in deny_exact or name.startswith(deny_prefix):
                continue
            # richiedi almeno read
            try:
                self.env[name].check_access_rights('read', raise_exception=True)
                allowed.append(name)
            except Exception:
                continue
        return sorted(set(allowed))

    def _model_catalog(self, models):
        res = {}
        for model in models[:200]:  # hard cap per payload
            try:
                fields = self.env[model].fields_get()
            except Exception:
                continue
            res[model] = {
                'fields': [k for k, v in fields.items() if v.get('type') in {
                    'char','text','selection','date','datetime','many2one','float','integer','boolean'}]
            }
        return res

    def _sanitize_domain(self, domain):
        if not isinstance(domain, list):
            return []
        safe = []
        for term in domain:
            if isinstance(term, (list, tuple)) and len(term) in (3, 4) and isinstance(term[0], str) and isinstance(term[1], str):
                safe.append(tuple(term))
        return safe

    # ---- LLM call ----
    def _llm_parse(self, prompt):
        ICP = self.env['ir.config_parameter'].sudo()
        url = ICP.get_param('ai_copilot.provider_url')
        api_key = ICP.get_param('ai_copilot.api_key')
        model_hint = ICP.get_param('ai_copilot.model') or ''
        temperature = float(ICP.get_param('ai_copilot.temperature') or 0.0)
        timeout = int(ICP.get_param('ai_copilot.timeout') or 20)
        if not url or not api_key:
            return None

        allowed_models = self._allowed_models()
        catalog = self._model_catalog(allowed_models)

        payload = {
            'prompt': prompt,
            'hint_model': model_hint,
            'temperature': temperature,
            'allowed_models': allowed_models,
            'catalog': catalog,
            'expected': {
                'either': 'single or candidates',
                'model': 'string',
                'domain': 'list of tuples',
                'description': 'string',
                'candidates': [
                    {'model': 'string', 'domain': 'list', 'confidence': 'float'}
                ]
            }
        }

        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
            'User-Agent': 'odoo-ai-copilot/18.0'
        }
        data = json.dumps(payload).encode('utf-8')

        try:
            req = request.Request(url, data=data, headers=headers, method='POST')
            with request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode('utf-8')
                obj = json.loads(body)
        except error.HTTPError as e:
            self._log_llm("HTTPError", f"status={e.code}")
            return None
        except error.URLError as e:
            self._log_llm("URLError", str(e))
            return None
        except Exception as e:
            self._log_llm("Exception", str(e))
            return None

        # single result
        if isinstance(obj.get('model'), str) and isinstance(obj.get('domain'), list):
            sd = self._sanitize_domain(obj.get('domain'))
            if not sd:
                return None
            return {'model': obj['model'], 'domain': sd, 'description': obj.get('description') or ''}

        # multi candidates
        candidates = obj.get('candidates') or []
        if candidates:
            sanitized = []
            for c in candidates[:5]:
                m = c.get('model')
                d = self._sanitize_domain(c.get('domain'))
                conf = float(c.get('confidence') or 0.0)
                if isinstance(m, str) and m in allowed_models and d:
                    sanitized.append({'model': m, 'domain': d, 'confidence': conf})
            if sanitized:
                return {'candidates': sanitized, 'description': obj.get('description') or ''}
        return None

    def _log_llm(self, tag, message):
        self.env['ir.logging'].create({
            'name': f'ai.llm.{tag}',
            'type': 'server',
            'dbname': self._cr.dbname,
            'level': 'WARNING',
            'message': message,
            'path': __name__,
            'line': 0,
            'func': '_llm_parse',
        })
