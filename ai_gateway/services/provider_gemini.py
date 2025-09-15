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
        # ``GenerativeModel`` was introduced in newer versions of the
        # ``google-generativeai`` package.  Older releases only expose the
        # ``generate_text`` function.  To keep the provider compatible across
        # versions we detect the availability of ``GenerativeModel`` at runtime
        # and fall back to using ``generate_text`` if necessary.
        if hasattr(genai, 'GenerativeModel'):
            self._model = genai.GenerativeModel(self._modern_model_name())
            self._use_generate_text = False
        else:  # pragma: no cover - depends on external package version
            self._model = None
            self._use_generate_text = True

    def _legacy_model_name(self):  # pragma: no cover - depends on external package version
        """Return a model name compatible with the legacy ``generate_text`` API."""
        legacy_prefixes = ('models/', 'tunedModels/')
        if self.model_name.startswith(legacy_prefixes):
            return self.model_name
        return f'models/{self.model_name}'

    def _modern_model_name(self):
        """Return a model name compatible with ``GenerativeModel``.

        The modern client accepts bare model identifiers (e.g.
        ``gemini-1.5-flash``).  However, configuration entries may still use
        the REST-style ``models/`` prefix.  Passing such a value directly to
        :class:`~google.generativeai.GenerativeModel` results in a ``404``
        error ("Requested entity was not found").  To remain compatible with
        both formats we strip the legacy prefix when present.
        """

        if self.model_name.startswith('models/'):
            return self.model_name[len('models/'):]
        return self.model_name

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
        if getattr(self, '_use_generate_text', False):  # pragma: no cover - fallback path
            prompt_txt = "\n\n".join(parts)
            resp = self._retry(
                genai.generate_text,
                model=self._legacy_model_name(),
                prompt=prompt_txt,
            )
            text = getattr(resp, 'result', '') or getattr(resp, 'text', '') or ''
            meta = getattr(resp, 'to_dict', lambda: {})()
        else:
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
