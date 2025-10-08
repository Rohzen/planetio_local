from odoo import models

from .provider_claude import ClaudeProvider
from .provider_gemini import GeminiProvider


def _chunk_text(text, max_chars):
    if not text:
        return []
    chunks = []
    step = max(1000, max_chars)
    for i in range(0, len(text), step):
        chunks.append(text[i : i + step])
    return chunks


def _decode_bytes(raw):
    if not raw:
        return ""
    try:
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        return raw.decode("latin-1", errors="ignore")


def _pdf_to_text(raw):
    import io

    if not raw:
        return ""
    buffer = io.BytesIO(raw)
    try:  # pragma: no cover - optional dependency
        from pdfminer.high_level import extract_text

        return extract_text(buffer) or ""
    except Exception:
        buffer.seek(0)
        try:  # pragma: no cover - optional dependency
            import PyPDF2

            reader = PyPDF2.PdfReader(buffer)
            texts = []
            for page in getattr(reader, "pages", []) or []:
                page_text = page.extract_text() or ""
                if page_text:
                    texts.append(page_text)
            return "\n".join(texts)
        except Exception:
            return ""


def _docx_to_text(raw):
    import io
    import zipfile
    from xml.etree import ElementTree

    if not raw:
        return ""
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            xml = zf.read("word/document.xml")
    except Exception:
        return ""

    try:
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        root = ElementTree.fromstring(xml)
        paragraphs = []
        for para in root.findall(".//w:p", ns):
            texts = [node.text for node in para.findall(".//w:t", ns) if node.text]
            if texts:
                paragraphs.append("".join(texts))
        return "\n".join(paragraphs)
    except Exception:
        return ""


def _attachment_to_text(env, att):
    import base64

    mimetype = (att.mimetype or "").lower()
<<<<<<< HEAD
    name = (att.name or "").lower()
    raw = base64.b64decode(att.datas or b"")

    if mimetype.startswith("text/") or mimetype in ("application/json", "application/xml"):
=======
    if ";" in mimetype:
        mimetype = mimetype.split(";", 1)[0].strip()
    name = (att.name or "").lower()
    raw = base64.b64decode(att.datas or b"")

    if (
        mimetype.startswith("text/")
        or mimetype in ("application/json", "application/xml")
        or mimetype.endswith("+json")
        or mimetype.endswith("+xml")
        or name.endswith((".json", ".xml"))
    ):
>>>>>>> 823bb1258a0473c1135fe37802bcf0567c9472f2
        return _decode_bytes(raw)

    if mimetype == "application/pdf" or name.endswith(".pdf"):
        return _pdf_to_text(raw)

    if mimetype in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    ) or name.endswith(".docx"):
        text = _docx_to_text(raw)
        if text:
            return text
        # legacy doc files might still be plain text when exported
        return _decode_bytes(raw)

    if mimetype in ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "text/csv") or name.endswith(".csv"):
        return _decode_bytes(raw)

    return ""

class AiGatewayService(models.AbstractModel):
    _name = 'ai.gateway.service'
    _description = 'AI Gateway Service'

    def _get_provider(self, provider_key=None):
        provider_key = provider_key or self.env['ir.config_parameter'].sudo().get_param('ai_gateway.default_provider', 'gemini')
        if provider_key == 'gemini':
            return GeminiProvider(self.env)
        if provider_key == 'claude':
            return ClaudeProvider(self.env)
        raise ValueError('Provider non supportato: %s' % provider_key)

    def run_request(self, req):
        provider = self._get_provider(req.provider)
        max_chars = int(self.env['ir.config_parameter'].sudo().get_param('ai_gateway.max_chunk_chars', 20000))
        system_instruction = "Sei un analista ambientale esperto. Fornisci risposte chiare e verificabili."

        if req.task_type == 'summarize':
            texts = []
            for att in req.attachment_ids:
                txt = _attachment_to_text(self.env, att)
                if txt:
                    header = att.name or att.display_name or "Documento senza nome"
                    texts.append(f"### {header}\n{txt}")
            full = "\n\n".join(texts) if texts else (req.payload or '')
            chunks = _chunk_text(full, max_chars)
            return provider.summarize_chunks(chunks, system_instruction=system_instruction)
        else:
            prompt = req.payload or ''
            return provider.generate(prompt, system_instruction=system_instruction)
