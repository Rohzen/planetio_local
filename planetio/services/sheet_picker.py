
from odoo import models
import base64, io, re, json as _json
from openpyxl import load_workbook

def _norm(s):
    return re.sub(r"\s+"," ", (s or "").strip().lower())

class ExcelImportService(models.AbstractModel):
    _name = "excel.import.service"
    _description = "Excel Import Service"

    # NOTE: lasciamo intatte le funzioni di parsing/rilevazione header che hai già nel tuo modulo.
    # Qui patchiamo solo create_records per creare 1 dichiarazione + N linee.

    def create_records(self, job):
        Line = self.env["eudr.declaration.line"]
        Decl = self.env["eudr.declaration"]

        rows = _json.loads(job.result_json or "[]")
        base_name = job.attachment_id.name or "EUDR"

        # crea la dichiarazione singola per il file
        decl = Decl.create({
            "name": base_name,
            "source_attachment_id": job.attachment_id.id,
        })

        count = 0
        for idx, r in enumerate(rows, start=1):
            if not any(r.values()):
                continue

            # sanitize geo_type
            if r.get("geo_type") not in ("point", "polygon", None, False):
                r.pop("geo_type", None)

            # ensure line name
            line_name = r.get("name") or r.get("farm_name") or r.get("farmer_name") or f"{base_name} - row {idx}"

            vals = dict(r)
            vals.update({
                "declaration_id": decl.id,
                "name": line_name,
            })
            Line.create(vals)
            count += 1

        # opzionale: scrivi un riassunto a livello dichiarazione (es. area totale) se vuoi
        return count
