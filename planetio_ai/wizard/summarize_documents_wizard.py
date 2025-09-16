from odoo import _, fields, models
import base64
import io
import logging

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


_logger = logging.getLogger(__name__)


class PlanetioSummarizeWizard(models.Model):
    _inherit = "eudr.declaration"

    def _summary_to_pdf(self, text, record):
        """Convert the AI summary into a nicely formatted PDF."""

        pdf_bytes, mimetype = self._summary_to_pdf_qweb(text, record)
        if pdf_bytes:
            return pdf_bytes, mimetype
        return self._summary_to_pdf_reportlab(text)

    def _summary_to_pdf_qweb(self, text, record):
        """Render the summary using the dedicated QWeb report.

        Returns ``(bytes, mimetype)`` when the rendering succeeds and
        ``(None, None)`` otherwise so that the caller can gracefully fall back
        to the ReportLab implementation or to raw text.
        """

        if not (text and record and record.id):
            return None, None

        report = self.env.ref(
            "planetio_ai.action_report_ai_summary", raise_if_not_found=False
        )
        if not report:
            return None, None

        try:
            data = self._prepare_summary_data(text, record)
            pdf_bytes, _ = report._render_qweb_pdf([record.id], data=data)
            return pdf_bytes, "application/pdf"
        except Exception:  # pragma: no cover - handled via fallback
            _logger.exception("Falling back to ReportLab for AI summary rendering")
            return None, None

    def _summary_to_pdf_reportlab(self, text):
        """Fallback ReportLab-based implementation for PDF summaries."""

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

    def _prepare_summary_data(self, text, record):
        """Convert the AI text response into data consumable by QWeb."""

        blocks = self._prepare_summary_blocks(text)
        generated_on = fields.Datetime.context_timestamp(record, fields.Datetime.now())

        summary = {
            "title": _("AI Document Summary"),
            "record_label": _("Declaration"),
            "record_name": record.display_name,
            "generated_on_label": _("Generated on"),
            "generated_on": generated_on,
            "blocks": blocks,
            "raw_label": _("Original AI response"),
            "raw_text": text.strip(),
            "empty_label": _("No summary content was returned by the AI service."),
        }

        return {"doc_data": {record.id: summary}}

    def _prepare_summary_blocks(self, text):
        """Parse the summary into a list of semantic blocks for QWeb."""

        blocks = []
        bullet_buffer = []
        paragraph_buffer = []
        table_buffer = []

        def flush_paragraph():
            nonlocal paragraph_buffer
            if not paragraph_buffer:
                return
            paragraph = " ".join(paragraph_buffer)
            blocks.append({"type": "paragraph", "text": paragraph})
            paragraph_buffer = []

        def flush_bullets():
            nonlocal bullet_buffer
            if not bullet_buffer:
                return
            blocks.append({"type": "bullets", "items": bullet_buffer[:]})
            bullet_buffer = []

        def flush_table():
            nonlocal table_buffer
            if not table_buffer:
                return
            filtered_rows = [
                row for row in table_buffer if not self._is_table_separator_row(row)
            ]
            table_buffer = []
            if not filtered_rows:
                return
            header = filtered_rows[0]
            rows = filtered_rows[1:] if len(filtered_rows) > 1 else []
            blocks.append({"type": "table", "header": header, "rows": rows})

        for raw_line in text.replace("\r\n", "\n").split("\n"):
            line = raw_line.strip()
            if not line:
                flush_paragraph()
                flush_bullets()
                flush_table()
                continue

            if line[0] in {"-", "*", "•"}:
                flush_paragraph()
                flush_table()
                bullet_text = line.lstrip("-*• ").strip()
                if bullet_text:
                    bullet_buffer.append(bullet_text)
                continue

            table_row = self._parse_table_row(line)
            if table_row:
                flush_paragraph()
                flush_bullets()
                table_buffer.append(table_row)
                continue

            flush_bullets()
            flush_table()

            if self._is_header_line(line):
                flush_paragraph()
                blocks.append({"type": "header", "text": line.rstrip(":")})
            else:
                paragraph_buffer.append(line)

        flush_paragraph()
        flush_bullets()
        flush_table()

        return blocks

    @staticmethod
    def _parse_table_row(line):
        """Return a list of cells when ``line`` looks like a Markdown table."""

        stripped = line.strip()
        if "|" not in stripped:
            return []
        raw_cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(raw_cells) < 2:
            return []
        if not any(cell for cell in raw_cells):
            return []
        if not any(any(ch.isalnum() for ch in cell) for cell in raw_cells):
            return []
        return raw_cells

    @staticmethod
    def _is_table_separator_row(row):
        """Detect rows made only of separators (``----`` or ``====``)."""

        if not row:
            return True
        for cell in row:
            cleaned = cell.replace(" ", "")
            if not cleaned:
                continue
            if any(ch not in "-=_–—" for ch in cleaned):
                return False
        return True

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

            pdf_bytes, mimetype = self._summary_to_pdf(summary, rec)

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
