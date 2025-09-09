from odoo import api, fields, models, _

class AiChatCandidate(models.TransientModel):
    _name = 'ai.chat.candidate'
    _description = 'Candidato NL→Domain'

    wizard_id = fields.Many2one('ai.chat.wizard', required=True, ondelete='cascade')
    model_name = fields.Char(string='Modello', required=True)
    domain_text = fields.Text(string='Dominio', required=True)
    confidence = fields.Float(string='Confidence')
    result_count = fields.Integer(string='Record')
    selected = fields.Boolean(string='Seleziona')

class AiChatWizard(models.TransientModel):
    _name = "ai.chat.wizard"
    _description = "Chat NL→Domain con anteprima e azione"

    active_id = fields.Boolean(string='active_id')
    prompt = fields.Text(required=True, help="Scrivi cosa cerchi, es: 'trovami le fatture di ACME dal 01/07/2025 al 31/07/2025 pagate'")
    dry_run = fields.Boolean(default=True, help="Se attivo, mostra solo il dominio e il conteggio record")
    limit = fields.Integer(default=80)
    target_model = fields.Char(readonly=True)
    preview_domain = fields.Text(readonly=True)
    result_count = fields.Integer(readonly=True)
    description = fields.Char(readonly=True)

    candidate_ids = fields.One2many('ai.chat.candidate', 'wizard_id', string='Candidati')

    @api.onchange('prompt')
    def _onchange_prompt(self):
        if not self.prompt:
            return
        engine = self.env["ai.intent.engine"]
        parsed = engine.parse_prompt(self.prompt)
        self.candidate_ids = [(5, 0, 0)]
        self.target_model = False
        self.preview_domain = False
        self.result_count = 0
        if not parsed:
            self.description = _("Nessuna regola ha riconosciuto la richiesta")
            return
        self.description = parsed.get("description")

        # Intent speciale: prodotti sotto min riordino → calcolo ids
        if parsed.get("intent") == "reorder_below_min":
            ids = self._compute_products_below_reorder()
            domain = [("id", "in", ids)] if ids else [("id", "=", 0)]
            self.target_model = "product.product"
            self.preview_domain = str(domain)
            try:
                self.result_count = self.env[self.target_model].search_count(domain)
            except Exception:
                self.result_count = 0
            return

        # multi-candidate
        candidates = parsed.get('candidates')
        if candidates:
            lines = []
            for c in candidates[:5]:
                model = c.get('model')
                domain = c.get('domain') or []
                count = 0
                try:
                    count = self.env[model].search_count(domain)
                except Exception:
                    count = 0
                lines.append((0, 0, {
                    'model_name': model,
                    'domain_text': str(domain),
                    'confidence': float(c.get('confidence') or 0.0),
                    'result_count': count,
                }))
            self.candidate_ids = lines
            return

        # single
        self.target_model = parsed.get("model")
        domain = parsed.get("domain", [])
        self.preview_domain = str(domain)
        if self.target_model:
            try:
                self.result_count = self.env[self.target_model].search_count(domain)
            except Exception:
                self.result_count = 0

        # logging
        self.env["ir.logging"].create({
            "name": "ai.chat.parse",
            "type": "server",
            "dbname": self._cr.dbname,
            "level": "INFO",
            "message": f"prompt={self.prompt} model={self.target_model} domain={self.preview_domain} count={self.result_count}",
            "path": __name__,
            "line": 0,
            "func": "_onchange_prompt",
        })

    def _get_selection(self):
        # restituisce (model, domain_list)
        if self.candidate_ids:
            cand = next((c for c in self.candidate_ids if c.selected), None) or self.candidate_ids[:1]
            cand = cand if isinstance(cand, models.BaseModel) else cand[0]
            try:
                domain = eval(cand.domain_text or '[]', {"__builtins__": {}}, {})
            except Exception:
                domain = []
            return cand.model_name, domain
        try:
            domain = eval(self.preview_domain or '[]', {"__builtins__": {}}, {})
        except Exception:
            domain = []
        return self.target_model, domain

    def _reparse_and_fill(self):
        """Ricalcola il dominio lato server (senza affidarsi all'onchange) e scrive i campi."""
        self.ensure_one()
        engine = self.env["ai.intent.engine"]
        parsed = engine.parse_prompt(self.prompt or "")
        # reset base
        vals = {
            "target_model": False,
            "preview_domain": False,
            "result_count": 0,
            "description": parsed.get("description") if parsed else _("Nessuna regola ha riconosciuto la richiesta"),
        }
        candidate_lines = [(5, 0, 0)]

        if parsed:
            # intent speciale (riordino)
            if parsed.get("intent") == "reorder_below_min":
                ids = self._compute_products_below_reorder()
                domain = [("id", "in", ids)] if ids else [("id", "=", 0)]
                vals.update({
                    "target_model": "product.product",
                    "preview_domain": str(domain),
                })
                try:
                    vals["result_count"] = self.env["product.product"].search_count(domain)
                except Exception:
                    pass

            # candidates multipli
            elif parsed.get("candidates"):
                for c in (parsed.get("candidates") or [])[:5]:
                    model = c.get("model")
                    domain = c.get("domain") or []
                    count = 0
                    try:
                        count = self.env[model].search_count(domain)
                    except Exception:
                        pass
                    candidate_lines.append((0, 0, {
                        "model_name": model,
                        "domain_text": str(domain),
                        "confidence": float(c.get("confidence") or 0.0),
                        "result_count": count,
                    }))

            # singolo
            else:
                model = parsed.get("model")
                domain = parsed.get("domain") or []
                vals.update({
                    "target_model": model,
                    "preview_domain": str(domain),
                })
                try:
                    vals["result_count"] = self.env[model].search_count(domain)
                except Exception:
                    pass

        # scrivi tutto (campi + candidati)
        self.write(vals)
        if candidate_lines != [(5, 0, 0)]:
            self.write({"candidate_ids": candidate_lines})
        else:
            self.write({"candidate_ids": [(5, 0, 0)]})

        return vals  # utile a chi chiama

    def action_preview(self):
        """Ricalcola, salva i valori e mostra una notifica; lascia aperto il wizard."""
        self.ensure_one()
        vals = self._reparse_and_fill()
        model = vals.get("target_model") or (self.candidate_ids[:1].model_name if self.candidate_ids else False)
        # prova a ricavare il dominio mostrabile
        domain_text = vals.get("preview_domain")
        if not domain_text and self.candidate_ids:
            domain_text = self.candidate_ids[0].domain_text

        # notifica 'sticky' con dominio
        self.env["ir.logging"].create({
            "name": "ai.chat.preview",
            "type": "server",
            "dbname": self._cr.dbname,
            "level": "INFO",
            "message": f"preview model={model} domain={domain_text}",
            "path": __name__,
            "line": 0,
            "func": "action_preview",
        })

        # torna allo stesso wizard (così i campi restano popolati)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Anteprima dominio"),
                "message": f"{self.description or ''}\nModel: {model or '—'}\nDomain: {domain_text or '[]'}",
                "sticky": True,
            },
        }

    def action_execute(self):
        """Apre i risultati; non dipende dall'onchange, usa i valori salvati o ricalcola al volo se serve."""
        self.ensure_one()
        # se non ci sono valori (es. apertura diretta), ricalcola
        if not self.preview_domain and not self.candidate_ids and not self.target_model:
            self._reparse_and_fill()

        model, domain = self._get_selection()
        if not model:
            return {'type': 'ir.actions.act_window_close'}

        action = {
            "type": "ir.actions.act_window",
            "name": self.description or model,
            "res_model": model,
            "view_mode": "list,form",
            "domain": domain,
            "target": "current",
            "context": {"search_default_filter_generated": 1},
        }
        if self.limit and self.limit > 0:
            action["limit"] = self.limit

        self.env["ir.logging"].create({
            "name": "ai.chat.execute",
            "type": "server",
            "dbname": self._cr.dbname,
            "level": "INFO",
            "message": f"execute model={model} domain={domain} limit={self.limit}",
            "path": __name__,
            "line": 0,
            "func": "action_execute",
        })
        return action

    def _compute_products_below_reorder(self):
        Rule = self.env["stock.warehouse.orderpoint"].sudo()
        Product = self.env["product.product"].sudo()
        rules = Rule.search([])
        ids = []
        for r in rules:
            product = Product.browse(r.product_id.id)
            qty = product.qty_available
            if qty < r.product_min_qty:
                ids.append(product.id)
        return list(set(ids))
