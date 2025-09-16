from odoo import _, fields, models
import base64
import io
import json
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

        deforestation_feedback = self._prepare_deforestation_feedback(record)

        pdf_bytes, mimetype = self._summary_to_pdf_qweb(
            text, record, deforestation_feedback=deforestation_feedback
        )
        if pdf_bytes:
            return pdf_bytes, mimetype
        return self._summary_to_pdf_reportlab(text, deforestation_feedback)

    def _summary_to_pdf_qweb(self, text, record, deforestation_feedback=None):
        """Render the summary using the dedicated QWeb report.

        Returns ``(bytes, mimetype)`` when the rendering succeeds and
        ``(None, None)`` otherwise so that the caller can gracefully fall back
        to the ReportLab implementation or to raw text.
        """

        has_text = bool(text and text.strip())
        has_deforestation = bool(
            deforestation_feedback and deforestation_feedback.get("blocks")
        )
        if not (record and record.id and (has_text or has_deforestation)):
            return None, None

        report = self.env.ref(
            "planetio_ai.action_report_ai_summary", raise_if_not_found=False
        )
        if not report:
            return None, None

        try:
            data = self._prepare_summary_data(
                text, record, deforestation_feedback=deforestation_feedback
            )
            pdf_bytes, _ = report._render_qweb_pdf([record.id], data=data)
            return pdf_bytes, "application/pdf"
        except Exception:  # pragma: no cover - handled via fallback
            _logger.exception("Falling back to ReportLab for AI summary rendering")
            return None, None

    def _summary_to_pdf_reportlab(self, text, deforestation_feedback=None):
        """Fallback ReportLab-based implementation for PDF summaries."""

        deforestation_text = ""
        if deforestation_feedback:
            deforestation_text = (
                deforestation_feedback.get("plain_text") or ""
            ).strip()

        combined_text = (text or "").strip()
        if deforestation_text:
            combined_text = (
                f"{combined_text}\n\n{deforestation_text}"
                if combined_text
                else deforestation_text
            )

        if not SimpleDocTemplate:
            return combined_text.encode("utf-8"), "text/plain"

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

        for raw_line in combined_text.replace("\r\n", "\n").split("\n"):
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

    def _prepare_summary_data(self, text, record, deforestation_feedback=None):
        """Convert the AI text response into data consumable by QWeb."""

        blocks = self._prepare_summary_blocks(text)
        defor_blocks = []
        if deforestation_feedback:
            defor_blocks = deforestation_feedback.get("blocks") or []
        if defor_blocks:
            blocks = defor_blocks + blocks
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

        if deforestation_feedback:
            summary["deforestation"] = {
                "line_count": deforestation_feedback.get("line_count", 0),
                "total_alerts": deforestation_feedback.get("total_alerts", 0),
                "lines": deforestation_feedback.get("lines", []),
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

    def _prepare_deforestation_feedback(self, record):
        """Collect deforestation alerts linked to the declaration ``record``."""

        if not record:
            return {}

        lines = getattr(record, "line_ids", self.env["eudr.declaration.line"])
        feedback_lines = []
        total_alerts = 0

        for line in lines:
            details_raw = getattr(line, "defor_details_json", None)
            details = {}
            if details_raw:
                try:
                    details = json.loads(details_raw)
                except Exception:
                    details = {}

            metrics = details.get("metrics") if isinstance(details, dict) else {}
            meta = details.get("meta") if isinstance(details, dict) else {}

            raw_alerts = []
            if isinstance(details, dict):
                raw_alerts = details.get("alerts") or []
                if not raw_alerts and isinstance(details.get("data"), dict):
                    raw_alerts = details["data"].get("alerts") or []
            if not isinstance(raw_alerts, list):
                raw_alerts = []

            formatted_alerts = [
                alert_text
                for alert_text in (
                    self._format_alert_entry(alert)
                    for alert in raw_alerts
                    if alert not in (None, "")
                )
                if alert_text
            ]

            message = (details.get("message") if isinstance(details, dict) else None) or (
                getattr(line, "external_message", "") or ""
            )
            provider = (meta.get("provider") if isinstance(meta, dict) else None) or (
                getattr(line, "defor_provider", "") or ""
            )

            alert_count = None
            if isinstance(metrics, dict):
                alert_count = metrics.get("alert_count")
            if alert_count is None:
                line_alerts = getattr(line, "defor_alerts", None)
                if line_alerts is not None and line_alerts is not False:
                    alert_count = line_alerts

            area_ha = None
            if isinstance(metrics, dict):
                area_ha = metrics.get("area_ha_total")
            if area_ha is None:
                line_area = getattr(line, "defor_area_ha", None)
                if line_area is not None and line_area is not False:
                    area_ha = line_area

            has_data = any(
                (
                    bool(message),
                    bool(provider),
                    alert_count is not None,
                    bool(formatted_alerts),
                    area_ha is not None,
                )
            )
            if not has_data:
                continue

            line_name = getattr(line, "display_name", None) or getattr(line, "name", None)
            line_name = line_name or str(line.id)

            if alert_count is not None:
                try:
                    total_alerts += int(float(alert_count))
                except Exception:
                    pass

            feedback_lines.append(
                {
                    "line_id": line.id,
                    "name": line_name,
                    "provider": provider or "",
                    "alert_count": alert_count,
                    "area_ha": area_ha,
                    "message": message or "",
                    "alerts": formatted_alerts,
                }
            )

        if not feedback_lines:
            return {}

        feedback = {
            "lines": feedback_lines,
            "total_alerts": total_alerts,
            "line_count": len(feedback_lines),
        }

        blocks = self._build_deforestation_blocks(feedback)
        feedback["blocks"] = blocks
        feedback["plain_text"] = self._blocks_to_plain_text(blocks)
        return feedback

    def _build_deforestation_blocks(self, feedback):
        """Create summary blocks describing deforestation feedback."""

        if not feedback:
            return []

        lines = feedback.get("lines") or []
        if not lines:
            return []

        blocks = []
        total_alerts = feedback.get("total_alerts", 0)
        line_count = feedback.get("line_count", len(lines))

        blocks.append({"type": "header", "text": _("Deforestation alerts summary")})
        if total_alerts:
            summary_text = _("%(count)s alert(s) detected across %(lines)s line(s).") % {
                "count": total_alerts,
                "lines": line_count,
            }
        else:
            summary_text = _(
                "The latest deforestation analysis reported no alerts for the processed lines."
            )
        blocks.append({"type": "paragraph", "text": summary_text})

        table_rows = []
        header = [
            _("Line"),
            _("Provider"),
            _("Alerts"),
            _("Area (ha)"),
            _("Message"),
        ]
        for line in lines:
            table_rows.append(
                [
                    str(line.get("name") or "-"),
                    str(line.get("provider") or "-"),
                    self._format_alert_count(line.get("alert_count")),
                    self._format_area(line.get("area_ha")),
                    str(line.get("message") or "-"),
                ]
            )
        blocks.append({"type": "table", "header": header, "rows": table_rows})

        for line in lines:
            alerts = line.get("alerts") or []
            if not alerts:
                continue
            title = _("Alerts for %s") % (line.get("name") or line.get("line_id"))
            blocks.append({"type": "header", "text": title})
            limited = list(alerts[:10])
            if len(alerts) > 10:
                limited.append(
                    _("...and %(count)s more alert(s).")
                    % {"count": len(alerts) - 10}
                )
            blocks.append({"type": "bullets", "items": limited})

        return blocks

    @staticmethod
    def _blocks_to_plain_text(blocks):
        """Convert summary blocks into a plaintext representation."""

        if not blocks:
            return ""

        lines = []
        for block in blocks:
            btype = block.get("type")
            if btype == "header":
                text = block.get("text")
                if text:
                    if lines:
                        lines.append("")
                    lines.append(str(text))
            elif btype == "paragraph":
                text = block.get("text")
                if text:
                    lines.append(str(text))
            elif btype == "bullets":
                for item in block.get("items", []):
                    if item:
                        lines.append(f"- {item}")
            elif btype == "table":
                header = block.get("header", [])
                rows = block.get("rows", [])
                if header:
                    lines.append(" | ".join(str(cell) for cell in header))
                for row in rows:
                    lines.append(" | ".join(str(cell) for cell in row))
        return "\n".join(lines)

    @staticmethod
    def _format_alert_count(value):
        if value is None or value is False or value == "":
            return "-"
        try:
            number = float(value)
        except Exception:
            return str(value)
        if number.is_integer():
            return str(int(number))
        return f"{number:.2f}"

    @staticmethod
    def _format_area(value):
        if value is None or value is False or value == "":
            return "-"
        try:
            number = float(value)
        except Exception:
            return str(value)
        return f"{number:.2f}"

    def _format_alert_entry(self, alert):
        if isinstance(alert, dict):
            preferred_keys = [
                ("alert_id", _("Alert ID")),
                ("id", _("Alert ID")),
                ("date", _("Date")),
                ("start_date", _("Start date")),
                ("end_date", _("End date")),
                ("confidence", _("Confidence")),
                ("intensity", _("Intensity")),
                ("area_ha", _("Area (ha)")),
                ("areaHa", _("Area (ha)")),
            ]
            parts = []
            for key, label in preferred_keys:
                if key not in alert:
                    continue
                value = alert.get(key)
                if value in (None, "", [], {}):
                    continue
                if key in {"area_ha", "areaHa"}:
                    value = self._format_area(value)
                parts.append(f"{label}: {value}")

            if not parts:
                for key, value in list(alert.items())[:3]:
                    if value in (None, "", [], {}):
                        continue
                    parts.append(f"{key}: {value}")

            if parts:
                return ", ".join(parts)

            try:
                return json.dumps(alert, ensure_ascii=False)
            except Exception:
                return str(alert)

        return str(alert)

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
