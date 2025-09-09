import re
from datetime import date, datetime
from odoo import models

DATE_PAT = r"(\\d{4}-\\d{2}-\\d{2}|\\d{2}/\\d{2}/\\d{4})"

def _parse_date(s):
    # accetta YYYY-MM-DD o DD/MM/YYYY
    if not s:
        return None
    s = s.strip()
    try:
        if "/" in s:
            return datetime.strptime(s, "%d/%m/%Y").date().isoformat()
        return datetime.strptime(s, "%Y-%m-%d").date().isoformat()
    except Exception:
        return None

class AiIntentEngine(models.AbstractModel):
    _name = "ai.intent.engine"
    _description = "Regole di parsing NL→Domain, con hook a LLM esterno"

    def _llm_parse(self, prompt):
        """Hook per integrare un provider LLM esterno.
        Deve restituire un dict come:
        {
          'model': 'account.move',
          'domain': [('move_type','in',['in_invoice','in_refund']), ...],
          'description': 'Fatture fornitore ACME tra 2025-07-01 e 2025-07-31 pagate'
        }
        oppure:
        {
          'candidates': [{'model':'...', 'domain':[...], 'confidence': 0.87}, ...],
          'description': '...'
        }
        Se non configurato, restituisce None.
        """
        return None

    def parse_prompt(self, prompt):
        """Prima prova con regole deterministiche, poi delega a LLM.
        Se il provider restituisce 'candidates', pass-through per scelta utente nel wizard.
        """
        res = self._rule_based_parse(prompt or "")
        if res:
            return res
        out = self._llm_parse(prompt)
        if not out:
            return None
        if out.get('candidates'):
            return {'candidates': out['candidates'], 'description': out.get('description') or ''}
        return out

    # ------------------------
    # Regole base in italiano
    # ------------------------
    def _rule_based_parse(self, prompt):
        p = (prompt or "").lower().strip()

        # 1) Contabilità: fatture fornitore tra due date, opz. stato pagate/aperte
        # es: "trovami tutte le fatture di ACME dal 01/07/2025 al 31/07/2025 solo pagate"
        m = re.search(r"fattur[ae].*?di\\s+(.+?)\\s+(?:dal|da)\\s+" + DATE_PAT + r"\\s+(?:al|fino al)\\s+" + DATE_PAT, p)
        if m:
            supplier = m.group(1).strip()
            d1 = _parse_date(m.group(2))
            d2 = _parse_date(m.group(3))
            domain = [
                ("move_type", "in", ["in_invoice", "in_refund"]),
                ("partner_id.name", "ilike", supplier),
            ]
            if d1:
                domain.append(("invoice_date", ">=", d1))
            if d2:
                domain.append(("invoice_date", "<=", d2))
            # stato
            if "pagate" in p or "pagati" in p:
                domain.append(("payment_state", "=", "paid"))
            elif "aperte" in p or "da pagare" in p:
                domain.append(("payment_state", "!=", "paid"))
            return {
                "model": "account.move",
                "domain": domain,
                "description": f"Fatture fornitore {supplier} tra {d1} e {d2}"
            }

        # 2) Magazzino: prodotti sotto scorta / sotto punto di riordino
        if "sotto scorta" in p or "sotto il punto di riordino" in p or "sotto punto di riordino" in p:
            return {
                "model": "product.product",
                "domain": [],  # placeholder; verrà calcolato dal wizard
                "description": "Prodotti sotto livello di riordino",
                "intent": "reorder_below_min",
            }

        # 3) Produzione: MO in ritardo / oltre deadline
        if "produzione" in p and ("ritardo" in p or "oltre" in p or "scadenza" in p):
            today = date.today().isoformat()
            return {
                "model": "mrp.production",
                "domain": [("state", "in", ["confirmed", "progress"]), ("date_deadline", "<", today)],
                "description": "Ordini di produzione in ritardo (deadline superata)",
            }

        # 4) Query semplici su partner/fornitori per P.IVA
        m2 = re.search(r"fornitor[ei]\\s+con\\s+partita iva\\s+([a-z0-9]+)", p)
        if m2:
            vat = m2.group(1)
            return {
                "model": "res.partner",
                "domain": [("supplier_rank", ">", 0), ("vat", "ilike", vat)],
                "description": f"Fornitori con P.IVA simile a {vat}",
            }

        return None
