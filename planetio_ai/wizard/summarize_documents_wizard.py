from odoo import _, fields, models
import ast
import base64
import io
import json
import logging
import re

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


DEFAULT_DEFORESTATION_PROMPT = (
    "Analizza tutti i documenti allegati relativi alla dichiarazione EUDR e "
    "riassumi le informazioni utili a valutare lo stato della deforestazione. "
    "La risposta finale deve includere bullet point chiari, lo stato della "
    "deforestazione, eventuali rischi o anomalie e, se disponibili dati "
    "numerici, una tabella in formato testo con gli indicatori principali."
)

DEFAULT_CORRECTIVE_ACTIONS_PROMPT = (
    "Indica le azioni correttive consigliate per mitigare i rischi individuati, "
    "specificando priorità, tempistiche e responsabilità quando possibile."
)


STRUCTURED_RESPONSE_INSTRUCTION = (
    "Restituisci esclusivamente JSON valido con la seguente struttura: "
    "{\"alerts\": [{\"field_id\": \"...\", \"field_label\": \"...\", \"description\": \"...\"}], "
    "\"actions\": [{\"field_id\": \"...\", \"field_label\": \"...\", \"description\": \"...\"}]}. "
    "Utilizza liste (anche vuote) per entrambi i campi, imposta field_id a null "
    "quando non disponibile e fornisci descrizioni chiare in forma di paragrafo."
)


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
    def _strip_ai_markup(text):
        """Remove simple Markdown markers used by the AI provider."""

        if text in (None, "", False):
            return ""
        if not isinstance(text, str):
            text = str(text)
        cleaned = text.replace("**", "").replace("__", "")
        cleaned = re.sub(r"`([^`]+)`", r"\\1", cleaned)
        return cleaned

    @classmethod
    def _clean_entry_text(cls, text):
        """Normalise raw AI text for display/storage purposes."""

        cleaned = cls._strip_ai_markup(text)
        if not cleaned:
            return ""
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip()

    @classmethod
    def _normalize_heading_token(cls, text):
        """Prepare a heading string for comparisons."""

        cleaned = cls._clean_entry_text(text)
        if not cleaned:
            return ""
        cleaned = cleaned.strip("# ")
        cleaned = cleaned.strip("-*• ")
        return cleaned.strip()

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

    _STRUCTURED_SECTION_KEY_ALIASES = {
        "alerts": {
            "alerts",
            "alert",
            "criticalalerts",
            "criticalissues",
            "criticalrisks",
            "issues",
            "risks",
            "warnings",
            "anomalies",
            "findings",
            "allerte",
            "allerta",
        },
        "actions": {
            "actions",
            "action",
            "actionitems",
            "actionpoints",
            "correctiveactions",
            "correctiveaction",
            "recommendedactions",
            "recommendations",
            "suggestions",
            "nextsteps",
            "mitigationactions",
            "mitigationmeasures",
            "remediationsteps",
            "followupactions",
            "azioni",
            "azionicorrettive",
        },
    }

    def _parse_ai_structured_response(self, text):
        """Try to extract structured alerts/actions from ``text``."""

        alerts = []
        actions = []
        if text in (None, "", False):
            return {"alerts": alerts, "actions": actions}

        if isinstance(text, (bytes, bytearray)):
            try:
                text = text.decode("utf-8")
            except Exception:
                text = text.decode("utf-8", errors="ignore")
        elif not isinstance(text, str):
            text = str(text)

        parsed = self._loads_json_like(text)
        if parsed is not None:
            structured = self._extract_structured_from_container(parsed)
            if structured["alerts"] or structured["actions"]:
                return structured

        return self._parse_structured_from_text(text)

    def _loads_json_like(self, text):
        """Return Python data parsed from ``text`` when it resembles JSON."""

        if not isinstance(text, str):
            return None

        cleaned = text.strip()
        if not cleaned:
            return None

        fence_match = re.match(r"```(?:json)?\s*(.+?)\s*```$", cleaned, re.DOTALL)
        if fence_match:
            cleaned = fence_match.group(1).strip()

        try:
            return json.loads(cleaned)
        except Exception:
            pass

        try:
            return ast.literal_eval(cleaned)
        except Exception:
            return None

    def _extract_structured_from_container(self, container):
        """Search ``container`` for alert/action sections."""

        empty = {"alerts": [], "actions": []}

        if isinstance(container, dict):
            candidates = [container]
            for key in ("data", "result", "response", "payload", "summary", "sections"):
                nested = container.get(key)
                if isinstance(nested, dict):
                    candidates.append(nested)
            for candidate in candidates:
                alerts = self._normalize_structured_entries(
                    self._extract_structured_entries(candidate, "alerts")
                )
                actions = self._normalize_structured_entries(
                    self._extract_structured_entries(candidate, "actions")
                )
                if alerts or actions:
                    return {"alerts": alerts, "actions": actions}

            for value in container.values():
                nested = self._extract_structured_from_container(value)
                if nested["alerts"] or nested["actions"]:
                    return nested

            return empty

        if isinstance(container, list):
            alerts = self._normalize_structured_entries(container)
            if alerts:
                return {"alerts": alerts, "actions": []}

            for item in container:
                nested = self._extract_structured_from_container(item)
                if nested["alerts"] or nested["actions"]:
                    return nested

            return empty

        if isinstance(container, str):
            nested = self._loads_json_like(container)
            if nested is not None:
                return self._extract_structured_from_container(nested)

        return empty

    def _extract_structured_entries(self, container, section):
        """Return the content of ``section`` from ``container`` handling aliases."""

        if not isinstance(container, dict):
            return []

        aliases = self._STRUCTURED_SECTION_KEY_ALIASES.get(section, {section})
        fallback = container.get(section)

        for key, value in container.items():
            if not isinstance(key, str):
                continue
            normalised = re.sub(r"[^a-z]", "", key.lower())
            if normalised not in aliases:
                continue
            if value in (None, "", False):
                continue
            if isinstance(value, (list, tuple, dict)) and not value:
                continue
            return value

        if fallback not in (None, "", False):
            if not isinstance(fallback, (list, tuple, dict)) or fallback:
                return fallback

        return []

    def _normalize_structured_entries(self, entries):
        """Normalise a list of entries into ``field_id``/``description`` dicts."""

        if isinstance(entries, dict):
            mapped_entries = []
            for key, value in entries.items():
                if isinstance(value, dict):
                    entry = dict(value)
                    entry.setdefault("field_id", key)
                elif isinstance(value, (list, tuple)):
                    entry = [key, *value]
                else:
                    entry = {"field_id": key, "description": value}
                mapped_entries.append(entry)
            entries = mapped_entries
        elif isinstance(entries, tuple):
            entries = list(entries)

        if isinstance(entries, (bytes, bytearray)):
            try:
                entries = entries.decode("utf-8")
            except Exception:
                entries = entries.decode("utf-8", errors="ignore")

        if isinstance(entries, str):
            entries = [entries]

        if not isinstance(entries, list):
            return []

        normalised = []
        for index, entry in enumerate(entries, start=1):
            normalised_entry = self._normalize_structured_entry(entry)
            if not normalised_entry:
                continue
            normalised_entry.setdefault("sequence", index * 10)
            normalised.append(normalised_entry)
        return normalised

    def _normalize_structured_entry(self, entry):
        """Turn ``entry`` into a dict with ``description`` and identifiers."""

        if entry in (None, "", [], {}):
            return {}

        result = {}

        if isinstance(entry, dict):
            description = (
                entry.get("description")
                or entry.get("paragraph")
                or entry.get("text")
                or entry.get("value")
                or entry.get("summary")
                or entry.get("action")
                or entry.get("actions")
                or entry.get("azioni")
                or entry.get("recommendation")
                or entry.get("recommendations")
                or entry.get("suggestion")
                or entry.get("suggestions")
                or entry.get("detail")
                or entry.get("details")
                or entry.get("note")
                or entry.get("notes")
                or entry.get("message")
                or entry.get("body")
                or entry.get("content")
            )
            description = self._clean_entry_text(description)
            if description:
                result["description"] = description

            for key in (
                "field_id",
                "field",
                "id",
                "line_id",
                "line",
                "identifier",
            ):
                value = self._clean_entry_text(entry.get(key))
                if value not in (None, ""):
                    result["field_id"] = value
                    break

            for key in (
                "field_label",
                "label",
                "field_name",
                "name",
                "line_name",
                "title",
            ):
                value = self._clean_entry_text(entry.get(key))
                if value not in (None, ""):
                    result["field_label"] = value
                    break

            if entry.get("sequence") not in (None, ""):
                result["sequence"] = entry.get("sequence")

        elif isinstance(entry, (list, tuple)):
            if not entry:
                return {}
            field_id = self._clean_entry_text(entry[0])
            description_parts = [
                self._clean_entry_text(part)
                for part in entry[1:]
                if part not in (None, "")
            ]
            description = " ".join(part for part in description_parts if part).strip()
            if description:
                result["description"] = description
            if field_id not in (None, ""):
                result["field_id"] = field_id

        else:
            cleaned = self._clean_entry_text(entry)
            if not cleaned:
                return {}
            cleaned = cleaned.lstrip("-*• ").strip()
            match = re.match(
                r"^(?P<label>[^:]+?)\s*[:\-–—]\s*(?P<body>.+)$",
                cleaned,
            )
            if match:
                label = match.group("label").strip()
                body = match.group("body").strip()
                if label:
                    result["field_id"] = label
                if body:
                    result["description"] = body
            else:
                result["description"] = cleaned

        if not result.get("description"):
            return {}

        return result

    def _parse_structured_from_text(self, text):
        """Fallback parser when the AI did not return JSON."""

        alerts = []
        actions = []
        if not text:
            return {"alerts": alerts, "actions": actions}

        current = None
        for raw_line in text.replace("\r\n", "\n").split("\n"):
            line = raw_line.strip()
            if not line:
                continue

            plain_line = self._strip_ai_markup(line)
            heading = self._normalize_heading_token(plain_line.rstrip(":"))
            heading_upper = heading.upper()
            heading_words = [
                word for word in re.split(r"\W+", heading_upper) if word
            ]
            heading_word_set = set(heading_words)
            if heading_upper in {
                "ALERTS",
                "DEFORESTATION ALERTS",
                "ALLERTE",
                "ALLERTA",
            } or (
                "ALERT" in heading_upper and len(heading_upper.split()) <= 5
            ):
                current = "alerts"
                continue

            if heading_upper in {
                "CORRECTIVE ACTIONS",
                "ACTIONS",
                "AZIONI CORRETTIVE",
            } or (
                {"CORRECTIVE", "CORRETTIVE"} & heading_word_set
                or (
                    {"ACTION", "ACTIONS", "AZIONI", "AZIONE"} & heading_word_set
                    and len(heading_word_set) <= 5
                )
            ):
                current = "actions"
                continue

            entry = self._normalize_structured_entry(plain_line)
            if not entry:
                continue

            if current == "actions":
                target = actions
            else:
                target = alerts
            entry.setdefault("sequence", len(target) * 10 + 10)
            target.append(entry)

        return {"alerts": alerts, "actions": actions}

    def _match_declaration_line(self, record, *identifiers):
        """Try to find a declaration line that matches the given identifiers."""

        lines = getattr(record, "line_ids", None)
        if not lines:
            return self.env["eudr.declaration.line"]

        try:
            line_list = list(lines)
        except TypeError:
            line_list = [lines]

        for identifier in identifiers:
            line = self._match_line_identifier(line_list, identifier)
            if line:
                return line

        return self.env["eudr.declaration.line"]

    @staticmethod
    def _match_line_identifier(lines, identifier):
        if identifier in (None, "", False):
            return None

        if isinstance(identifier, (int, float)):
            try:
                numeric_id = int(identifier)
            except Exception:
                numeric_id = None
            else:
                for line in lines:
                    if getattr(line, "id", None) == numeric_id:
                        return line

        identifier_str = str(identifier).strip()
        if not identifier_str:
            return None

        try:
            numeric_id = int(float(identifier_str))
        except Exception:
            numeric_id = None
        else:
            for line in lines:
                if getattr(line, "id", None) == numeric_id:
                    return line

        lowered = identifier_str.lower()
        for attr in (
            "external_uid",
            "farmer_id_code",
            "name",
            "display_name",
            "line_label",
        ):
            for line in lines:
                value = getattr(line, attr, None)
                if not value:
                    continue
                if str(value).strip().lower() == lowered:
                    return line

        return None

    def _prepare_feedback_records(self, record, entries):
        prepared = []
        for index, entry in enumerate(entries, start=1):
            description = (entry.get("description") or "").strip()
            if not description:
                continue

            identifier = entry.get("field_id")
            label = entry.get("field_label")
            line = self._match_declaration_line(record, identifier, label)

            values = {
                "sequence": entry.get("sequence") or index * 10,
                "description": description,
            }

            if identifier not in (None, "", False):
                values["field_identifier"] = str(identifier)

            if label not in (None, "", False):
                values["line_label"] = str(label)

            if line and getattr(line, "id", None):
                values["line_id"] = line.id
                if not values.get("line_label"):
                    values["line_label"] = getattr(line, "display_name", None) or getattr(
                        line, "name", None
                    )

            display_label = values.get("line_label") or values.get("field_identifier") or ""
            prepared.append({"vals": values, "label": display_label})

        return prepared

    def _store_ai_feedback(self, record, alerts, actions):
        alert_prepared = self._prepare_feedback_records(record, alerts)
        action_prepared = self._prepare_feedback_records(record, actions)

        vals = {}
        record_fields = getattr(record, "_fields", {}) or {}
        if "ai_alert_ids" in record_fields or hasattr(record, "ai_alert_ids"):
            commands = [(5, 0, 0)]
            commands.extend((0, 0, item["vals"]) for item in alert_prepared)
            vals["ai_alert_ids"] = commands

        if "ai_action_ids" in record_fields or hasattr(record, "ai_action_ids"):
            commands = [(5, 0, 0)]
            commands.extend((0, 0, item["vals"]) for item in action_prepared)
            vals["ai_action_ids"] = commands

        if vals:
            record.write(vals)

        return alert_prepared, action_prepared

    def _format_structured_summary(self, alerts, actions):
        sections = []

        if alerts:
            lines = [_("Detected alerts")]
            for item in alerts:
                vals = item.get("vals", {})
                label = item.get("label") or vals.get("line_label") or vals.get("field_identifier")
                description = vals.get("description") or ""
                if label:
                    lines.append(f"- {label}: {description}")
                else:
                    lines.append(f"- {description}")
            sections.append("\n".join(lines))

        if actions:
            lines = [_("Suggested corrective actions")]
            for item in actions:
                vals = item.get("vals", {})
                label = item.get("label") or vals.get("line_label") or vals.get("field_identifier")
                description = vals.get("description") or ""
                if label:
                    lines.append(f"- {label}: {description}")
                else:
                    lines.append(f"- {description}")
            sections.append("\n".join(lines))

        return "\n\n".join(section for section in sections if section).strip()

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
        icp = self.env["ir.config_parameter"].sudo()
        default_provider = (
            icp.get_param("ai_gateway.default_provider", "gemini") or "gemini"
        )

        deforestation_prompt = (
            icp.get_param("planetio_ai.prompt_deforestation_critical_issues")
            or DEFAULT_DEFORESTATION_PROMPT
        )
        corrective_prompt = (
            icp.get_param("planetio_ai.prompt_corrective_actions")
            or DEFAULT_CORRECTIVE_ACTIONS_PROMPT
        )

        payload_parts = [STRUCTURED_RESPONSE_INSTRUCTION]
        cleaned_deforestation = (deforestation_prompt or "").strip()
        cleaned_actions = (corrective_prompt or "").strip()
        if cleaned_deforestation:
            payload_parts.append("### Deforestation alerts")
            payload_parts.append(cleaned_deforestation)
        if cleaned_actions:
            payload_parts.append("### Corrective actions")
            payload_parts.append(cleaned_actions)
        payload_parts = [part for part in payload_parts if part]
        payload_text = "\n\n".join(payload_parts)
        for rec in self:
            if not rec.attachment_ids:
                continue

            req = AiRequest.create(
                {
                    "name": f"AI Summary for {rec.id}",
                    "provider": default_provider,
                    "task_type": "summarize",
                    "attachment_ids": [(6, 0, rec.attachment_ids.ids)],
                    "model_ref": f"{rec._name},{rec.id}",
                    "payload": payload_text,
                }
            )

            req.run_now()
            if getattr(req, "status", None) == "error":
                rec.message_post(body=f"AI request error: {req.error_message}")
                continue

            summary = req.response_text or ""
            structured = self._parse_ai_structured_response(summary)
            alerts = structured.get("alerts") or []
            actions = structured.get("actions") or []
            alert_prepared, action_prepared = self._store_ai_feedback(
                rec, alerts, actions
            )

            formatted_text = self._format_structured_summary(
                alert_prepared, action_prepared
            )
            combined_text = summary
            if formatted_text:
                formatted_text = formatted_text.strip()
                if summary and formatted_text and formatted_text != summary.strip():
                    combined_text = (
                        f"{formatted_text}\n\n{_('Original AI response')}\n{summary}"
                    )
                else:
                    combined_text = formatted_text or summary

            combined_text = (combined_text or "").strip()
            if not combined_text:
                continue

            pdf_bytes, mimetype = self._summary_to_pdf(combined_text, rec)

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
