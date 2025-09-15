from odoo import api, fields, models
import base64
import io

try:  # pragma: no cover - optional dependency
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import (
        ListFlowable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
    )
except Exception:  # pragma: no cover - handled gracefully at runtime
    colors = None
    ParagraphStyle = None
    SimpleDocTemplate = None
    Paragraph = None
    ListFlowable = None
    Spacer = None
    A4 = (595.27, 841.89)


class PlanetioSummarizeWizard(models.Model):
    _inherit = "eudr.declaration"

    def _summary_to_pdf(self, text):
        """Convert plain text summary to PDF bytes.

        Falls back to returning the raw text encoded if the ``reportlab``
        dependency is not available.  The caller is responsible for deciding
        the mimetype in that case.
        """

        if not SimpleDocTemplate:
            return text.encode("utf-8"), "text/plain"

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=40,
            rightMargin=40,
            topMargin=60,
            bottomMargin=60,
        )

        styles = getSampleStyleSheet()
        body_style = ParagraphStyle(
            "SummaryBody",
            parent=styles["BodyText"],
            leading=14,
            spaceAfter=6,
        )
        header_style = ParagraphStyle(
            "SummaryHeader",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            textColor=colors.HexColor("#2e7d32"),
            spaceBefore=12,
            spaceAfter=6,
        )
        bullet_style = ParagraphStyle(
            "SummaryBullet",
            parent=body_style,
            leftIndent=0,
            firstLineIndent=0,
            bulletIndent=0,
        )

        flowables = []
        bullet_buffer = []

        def add_spacer(height=12):
            if flowables and isinstance(flowables[-1], Spacer):
                return
            flowables.append(Spacer(1, height))

        def flush_bullets():
            nonlocal bullet_buffer
            if not bullet_buffer:
                return
            items = [Paragraph(item, bullet_style) for item in bullet_buffer]
            if items:
                flowables.append(
                    ListFlowable(
                        items,
                        bulletType="bullet",
                        leftIndent=16,
                        bulletFontName="Helvetica",
                        bulletFontSize=10,
                    )
                )
                add_spacer(6)
            bullet_buffer = []

        for raw_line in text.replace("\r\n", "\n").split("\n"):
            line = raw_line.strip()
            if not line:
                flush_bullets()
                add_spacer()
                continue

            if line[0] in {"-", "*", "•"}:
                bullet_text = line.lstrip("-*• ").strip()
                if bullet_text:
                    bullet_buffer.append(bullet_text)
                continue

            flush_bullets()

            if self._is_header_line(line):
                flowables.append(Paragraph(line.rstrip(":"), header_style))
            else:
                flowables.append(Paragraph(line, body_style))

        flush_bullets()

        if not flowables:
            flowables.append(Paragraph(" ", body_style))

        doc.build(flowables)
        buffer.seek(0)
        return buffer.getvalue(), "application/pdf"

    @staticmethod
    def _is_header_line(line):
        """Return ``True`` when a line should be styled as a header."""

        stripped = line.strip()
        if not stripped:
            return False
        if stripped.endswith(":"):
            return True
        words = stripped.split()
        if len(words) <= 6 and stripped.isupper():
            return True
        if len(words) <= 6 and stripped == stripped.title():
            if all(ch.isalpha() or ch.isspace() for ch in stripped):
                return True
        return False

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
                    "payload": (
                        "Analizza tutti i documenti allegati relativi alla dichiarazione EUDR e "
                        "riassumi le informazioni utili a valutare lo stato della deforestazione. "
                        "La risposta finale deve includere bullet point chiari, lo stato della "
                        "deforestazione, eventuali rischi o anomalie e, se disponibili dati "
                        "numerici, una tabella in formato testo con gli indicatori principali."
                    ),
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
