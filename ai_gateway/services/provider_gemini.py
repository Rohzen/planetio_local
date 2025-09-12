import google.generativeai as genai
import time

class GeminiProvider(object):
    def __init__(self, env):
        self.env = env
        self.api_key = env['ir.config_parameter'].sudo().get_param('ai_gateway.gemini_api_key')
        self.model_name = env['ir.config_parameter'].sudo().get_param('ai_gateway.gemini_model', default='gemini-1.5-flash')
        if not self.api_key:
            raise ValueError('Gemini API key mancante in Impostazioni')
        genai.configure(api_key=self.api_key)
        self._model = genai.GenerativeModel(self.model_name)

    def _retry(self, func, *args, **kwargs):
        backoff = 1.0
        for i in range(5):
            try:
                return func(*args, **kwargs)
            except Exception:
                if i == 4:
                    raise
                time.sleep(backoff)
                backoff *= 2

    def generate(self, prompt, system_instruction=None, **kwargs):
        parts = []
        if system_instruction:
            parts.append(system_instruction)
        parts.append(prompt)
        resp = self._retry(self._model.generate_content, parts)
        text = getattr(resp, 'text', '') or ''
        meta = getattr(resp, 'to_dict', lambda: {})()
        return {'text': text, 'meta': meta, 'tokens_in': 0, 'tokens_out': 0, 'cost': 0.0}

    def summarize_chunks(self, chunks, system_instruction=None, **kwargs):
        partial_summaries = []
        for idx, chunk in enumerate(chunks, 1):
            prompt = f"Riassumi concisamente il seguente testo (parte {idx}/{len(chunks)}), mantieni i numeri e gli elementi utili alla valutazione deforestazione:\n\n{chunk}"
            res = self.generate(prompt, system_instruction=system_instruction)
            partial_summaries.append(res['text'])
        merged_prompt = "Unisci i seguenti riassunti parziali in un unico executive summary con bullet point e una sezione 'Rischi/Anomalie':\n\n" + "\n\n".join(partial_summaries)
        final = self.generate(merged_prompt, system_instruction=system_instruction)
        return final
