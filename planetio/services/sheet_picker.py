# -*- coding: utf-8 -*-
# planetio/services/sheet_picker.py
from odoo import models, fields
import json as _json

class ExcelImportService(models.AbstractModel):
    _inherit = "excel.import.service"
    _description = "Excel Import Service patch"

    def _next_declaration_name(self, job):
        """
        Return a guaranteed non-empty, unique declaration name.
        """
        seq_codes = [
            "eudr.declaration",
            "planetio.eudr.declaration",
            "eudr.declaration.sequence",
        ]
        name = None
        for code in seq_codes:
            try:
                name = self.env["ir.sequence"].sudo().next_by_code(code)
            except Exception:
                name = None
            if name:
                break

        if not name:
            ts = fields.Datetime.now().strftime("%Y%m%d-%H%M%S")
            base = (getattr(job.attachment_id, "name", None) or "EUDR Import").rsplit(".", 1)[0]
            name = f"{base} [{ts}-{job.id}]"

        name = (name or "").strip() or f"EUDR {fields.Datetime.now().strftime('%Y%m%d-%H%M%S')}-{job.id}"
        return name

    def _extract_rows_from_job(self, job):
        """
        Prefer validated rows; fallback to preview; fallback to on-the-fly validation.
        Returns list of dicts.
        """
        rows = None
        # Prefer validated
        if getattr(job, "result_json", None):
            try:
                obj = job.result_json
                if isinstance(obj, str):
                    obj = _json.loads(obj)
                if isinstance(obj, dict) and "valid" in obj:
                    rows = obj["valid"]
                elif isinstance(obj, list):
                    rows = obj
            except Exception:
                rows = None
        # Fallback to preview
        if rows is None and getattr(job, "preview_json", None):
            try:
                obj = job.preview_json
                if isinstance(obj, str):
                    obj = _json.loads(obj)
                if isinstance(obj, list):
                    rows = obj
                elif isinstance(obj, dict) and "preview_rows" in obj:
                    rows = obj["preview_rows"]
            except Exception:
                rows = None
        # Final fallback: validate now
        if rows is None:
            try:
                rows = self.validate_rows(job).get("valid", [])
            except Exception:
                rows = []

        # Normalize to list[dict]
        safe_rows = []
        for r in rows or []:
            if isinstance(r, str):
                try:
                    r = _json.loads(r)
                except Exception:
                    continue
            if isinstance(r, dict):
                safe_rows.append(r)
        return safe_rows

    def create_records(self, job):
        """
        Create 1 eudr.declaration + N eudr.declaration.line from the validated rows.
        Stores external_uid for each line and binds the job to the declaration.
        """
        rows = self._extract_rows_from_job(job)
        if not rows:
            return 0

        Decl = self.env["eudr.declaration"]
        Line = self.env["eudr.declaration.line"]

        decl_name = self._next_declaration_name(job)
        decl = Decl.create({"name": decl_name})

        # Bind job to declaration (if the field exists)
        try:
            job.sudo().write({"declaration_id": decl.id})
        except Exception:
            pass

        base_name = (getattr(job.attachment_id, "name", None) or "EUDR Import").rsplit(".", 1)[0]

        count = 0
        for idx, r in enumerate(rows, start=1):
            # Skip empty rows (all values empty/None/[]/{})
            if not any(v for v in r.values() if v not in (None, "", [], {})):
                continue

            # Remove helper key; geometry contains the actual GeoJSON
            r.pop("geo_type", None)

            # Ensure line name
            line_name = (
                r.get("name")
                or r.get("farm_name")
                or r.get("farmer_name")
                or f"{base_name} - row {idx}"
            )

            vals = dict(r)
            vals.update({
                "declaration_id": decl.id,
                "name": line_name,
                "external_uid": f"job{job.id}-row{idx}",
            })
            Line.create(vals)
            count += 1

        return count
