from odoo import api, fields, models
import base64
import io

try:  # pragma: no cover - optional dependency
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
except Exception:  # pragma: no cover - handled gracefully at runtime
    canvas = None
    A4 = (595.27, 841.89)


class PlanetioSummarizeWizard(models.Model):
    _inherit = "eudr.declaration"

    def _summary_to_pdf(self, text):
        """Convert plain text summary to PDF bytes.

        Falls back to returning the raw text encoded if the ``reportlab``
        dependency is not available.  The caller is responsible for deciding
        the mimetype in that case.
        """

        if not canvas:
            return text.encode("utf-8"), "text/plain"

        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=A4)
        text_obj = c.beginText(40, A4[1] - 40)
        for line in text.splitlines():
            text_obj.textLine(line)
        c.drawText(text_obj)
        c.showPage()
        c.save()
        buffer.seek(0)
        return buffer.getvalue(), "application/pdf"

    def action_ai_analyze(self):
        """Summarise attached documents using the AI gateway service.

        For each declaration record, a new ``ai.request`` is created with all
        attachments and executed immediately.  The resulting text summary is
        turned into a PDF and stored back on the declaration as an attachment.
        """

        AiRequest = self.env["ai.request"]
        for rec in self:
            if not rec.attachment_ids:
                continue

            req = AiRequest.create(
                {
                    "name": f"AI Summary for {rec.id}",
                    "task_type": "summarize",
                    "attachment_ids": [(6, 0, rec.attachment_ids.ids)],
                    "model_ref": f"{rec._name},{rec.id}",
                    "payload": "Estrarre un riepilogo con i dati rilevanti alla deforestazione.",
                }
            )

            req.run_now()
            if getattr(req, "status", None) == "error":
                rec.message_post(body=f"AI request error: {req.error_message}")
                continue

            summary = req.response_text or ""
            if not summary:
                continue

            pdf_bytes, mimetype = self._summary_to_pdf(summary)

            self.env["ir.attachment"].create(
                {
                    "name": "ai_summary.pdf" if mimetype == "application/pdf" else "ai_summary.txt",
                    "type": "binary",
                    "datas": base64.b64encode(pdf_bytes),
                    "mimetype": mimetype,
                    "res_model": rec._name,
                    "res_id": rec.id,
                }
            )

        return True
