import json
import random
import time
from typing import Any, Dict, List, Optional

import requests

from .provider_base import ProviderBase


class ClaudeProvider(ProviderBase):
    """Simple Anthropic Claude client with retry helpers."""

    API_URL = "https://api.anthropic.com/v1/messages"
    DEFAULT_MODEL = "claude-3-sonnet-20240229"
    API_VERSION = "2023-06-01"

    def __init__(self, env):
        super().__init__(env)
        icp = env['ir.config_parameter'].sudo()
        self.api_key = icp.get_param('ai_gateway.claude_api_key')
        self.model_name = icp.get_param(
            'ai_gateway.claude_model', default=self.DEFAULT_MODEL
        ) or self.DEFAULT_MODEL
        self.max_output_tokens = int(
            icp.get_param('ai_gateway.claude_max_output_tokens', 1024) or 1024
        )
        if not self.api_key:
            raise ValueError("Claude API key mancante in Impostazioni")

    # ---------------- utils ----------------

    def _retry(self, func, *args, **kwargs):
        max_attempts = 5
        backoff = 1.0
        for attempt in range(1, max_attempts + 1):
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                msg = str(exc)
                transient = any(
                    hint in msg
                    for hint in [
                        '429',
                        '500',
                        '502',
                        '503',
                        '504',
                        'timeout',
                        'temporarily unavailable',
                    ]
                )
                if not transient or attempt == max_attempts:
                    raise
                time.sleep(backoff + random.uniform(0, 0.5))
                backoff *= 2

    def _prepare_payload(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            'model': self.model_name,
            'max_tokens': kwargs.get('max_tokens') or self.max_output_tokens,
            'messages': kwargs.get('messages')
            or [
                {
                    'role': 'user',
                    'content': prompt or '',
                }
            ],
        }
        if system_instruction:
            payload['system'] = system_instruction

        optional_keys = [
            'temperature',
            'top_p',
            'top_k',
            'metadata',
        ]
        for key in optional_keys:
            if key in kwargs and kwargs[key] is not None:
                payload[key] = kwargs[key]

        stop_sequences = kwargs.get('stop_sequences') or kwargs.get('stop')
        if stop_sequences:
            if isinstance(stop_sequences, (list, tuple)):
                payload['stop_sequences'] = list(stop_sequences)
            else:
                payload['stop_sequences'] = [stop_sequences]

        return payload

    def _request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        headers = {
            'x-api-key': self.api_key,
            'anthropic-version': self.API_VERSION,
            'content-type': 'application/json',
        }
        response = requests.post(
            self.API_URL,
            headers=headers,
            data=json.dumps(payload),
            timeout=90,
        )
        if response.status_code >= 400:
            raise RuntimeError(
                'AI request error (Claude %s): %s'
                % (response.status_code, response.text)
            )
        return response.json()

    def _extract_text(self, data: Dict[str, Any]) -> str:
        content = data.get('content')
        if isinstance(content, list):
            texts: List[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get('type') == 'text' and item.get('text'):
                    texts.append(item['text'])
            return ''.join(texts)
        if isinstance(content, str):
            return content
        return ''

    # ---------------- public API ----------------

    def generate(self, prompt, system_instruction=None, **kwargs):
        payload = self._prepare_payload(
            prompt, system_instruction=system_instruction, **kwargs
        )
        data = self._retry(self._request, payload)
        text = self._extract_text(data)
        usage = data.get('usage') or {}
        return {
            'text': text,
            'meta': data,
            'tokens_in': usage.get('input_tokens') or 0,
            'tokens_out': usage.get('output_tokens') or 0,
            'cost': 0.0,
        }

    def summarize_chunks(self, chunks, system_instruction=None, **kwargs):
        partial_summaries = []
        total = len(chunks) or 0
        for idx, chunk in enumerate(chunks, 1):
            prompt = (
                f"Riassumi concisamente il seguente testo (parte {idx}/{total}). "
                f"Mantieni numeri ed elementi utili alla valutazione deforestazione:\n\n{chunk}"
            )
            res = self.generate(
                prompt, system_instruction=system_instruction, **kwargs
            )
            partial_summaries.append((res.get('text') or '').strip())

        merged_prompt = (
<<<<<<< HEAD
            "Unisci i seguenti riassunti parziali in un unico executive summary con bullet point "
            "e una sezione 'Rischi/Anomalie'. Evita ripetizioni e mantieni i dati numerici:\n\n"
=======
            "Unisci i seguenti riassunti parziali in un unico executive summary con bullet point, "
            "aggiungi una sezione 'Rischi/Anomalie' e una sezione 'Azioni correttive' con interventi "
            "pratici e mirati. Evita ripetizioni e mantieni i dati numerici:\n\n"
>>>>>>> 823bb1258a0473c1135fe37802bcf0567c9472f2
            + "\n\n".join([s for s in partial_summaries if s])
        )
        final = self.generate(
            merged_prompt, system_instruction=system_instruction, **kwargs
        )
        return final
