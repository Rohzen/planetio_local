from odoo import models
from .provider_gemini import GeminiProvider

def _chunk_text(text, max_chars):
    if not text:
        return []
    chunks = []
    step = max(1000, max_chars)
    for i in range(0, len(text), step):
        chunks.append(text[i:i+step])
    return chunks

def _attachment_to_text(env, att):
    import base64
    mimetype = att.mimetype or ''
    raw = base64.b64decode(att.datas or b'')
    if mimetype.startswith('text/') or mimetype in ('application/json',):
        try:
            return raw.decode('utf-8', errors='ignore')
        except Exception:
            return raw.decode('latin-1', errors='ignore')
    return ''

class AiGatewayService(models.AbstractModel):
    _name = 'ai.gateway.service'
    _description = 'AI Gateway Service'

    def _get_provider(self, provider_key=None):
        provider_key = provider_key or self.env['ir.config_parameter'].sudo().get_param('ai_gateway.default_provider', 'gemini')
        if provider_key == 'gemini':
            return GeminiProvider(self.env)
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
                    texts.append(txt)
            full = "\n\n".join(texts) if texts else (req.payload or '')
            chunks = _chunk_text(full, max_chars)
            return provider.summarize_chunks(chunks, system_instruction=system_instruction)
        else:
            prompt = req.payload or ''
            return provider.generate(prompt, system_instruction=system_instruction)
