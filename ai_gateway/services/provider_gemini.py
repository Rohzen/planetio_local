import time
import random
import json
import requests
import google.generativeai as genai


class GeminiProvider(object):
    PREFERRED_MODELS = ["gemini-1.5-flash", "gemini-1.5-flash-8b", "gemini-1.5-pro"]
    REST_BASE = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, env):
        self.env = env
        self.api_key = env['ir.config_parameter'].sudo().get_param('ai_gateway.gemini_api_key')
        raw_model = env['ir.config_parameter'].sudo().get_param(
            'ai_gateway.gemini_model', default=self.PREFERRED_MODELS[0]
        )
        if not self.api_key:
            raise ValueError("Gemini API key mancante in Impostazioni")

        # prova a configurare il client; se è vecchio useremo il fallback REST
        self._client_ok = False
        try:
            genai.configure(api_key=self.api_key)
            self.model_name = self._normalize_to_bare_id(raw_model)
            if hasattr(genai, "GenerativeModel"):
                # alcune versioni vecchie hanno l'attributo ma poi 404 sui modelli gemini.
                # useremo comunque un tentativo con REST come fallback in generate().
                self._model = genai.GenerativeModel(self.model_name)
                self._use_generate_text = False
                self._client_ok = True
            else:
                # client davvero legacy → usa REST
                self._model = None
                self._use_generate_text = True  # segnala percorso non-moderno
        except Exception:
            # in caso di errore di import/config → andremo direttamente in REST
            self._model = None
            self._use_generate_text = True

    # ---------------- utils ----------------

    def _normalize_to_bare_id(self, model_id: str) -> str:
        if not model_id:
            return self.PREFERRED_MODELS[0]
        if "/models/" in model_id:
            # projects/.../locations/.../publishers/google/models/{id}
            model_id = model_id.split("/models/")[-1]
        if model_id.startswith("models/"):
            model_id = model_id[len("models/"):]
        # rimuovi eventuale @version
        return model_id.split("@")[0]

    def _retry(self, func, *args, **kwargs):
        max_attempts = 5
        backoff = 1.0
        for attempt in range(1, max_attempts + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                msg = str(e)
                transient = any(x in msg for x in ["429", "500", "502", "503", "504", "deadline", "timeout"])
                if not transient or attempt == max_attempts:
                    raise
                time.sleep(backoff + random.uniform(0, 0.5))
                backoff *= 2

    # ---------------- REST fallback ----------------

    def _rest_generate(self, parts, **kwargs):
        url = f"{self.REST_BASE}/models/{self.model_name}:generateContent?key={self.api_key}"
        payload = {"contents": [{"parts": [{"text": p} for p in parts]}]}
        # passa configurazioni opzionali se presenti (come da API)
        gen_cfg = kwargs.get("generation_config")
        if isinstance(gen_cfg, dict):
            payload.update(gen_cfg)
        safety = kwargs.get("safety_settings")
        if safety:
            payload["safetySettings"] = safety

        headers = {"Content-Type": "application/json"}
        resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=60)
        if resp.status_code == 404:
            raise RuntimeError(
                f"Model '{self.model_name}' non trovato (REST 404). "
                f"Controlla 'ai_gateway.gemini_model' oppure prova uno tra: "
                f"{', '.join(self.PREFERRED_MODELS)}. Body: {resp.text}"
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"AI request error (REST {resp.status_code}): {resp.text}")
        data = resp.json()
        # estrai testo primario
        text = ""
        try:
            cands = data.get("candidates") or []
            if cands and cands[0].get("content", {}).get("parts"):
                text = "".join(part.get("text", "") for part in cands[0]["content"]["parts"])
        except Exception:
            text = ""
        return {"text": text, "meta": data, "tokens_in": 0, "tokens_out": 0, "cost": 0.0}

    # ---------------- public API ----------------

    def generate(self, prompt, system_instruction=None, **kwargs):
        parts = []
        if system_instruction:
            parts.append(system_instruction)
        parts.append(prompt)

        # 1) prova client moderno se crediamo sia utilizzabile
        if self._client_ok:
            try:
                gen_kwargs = {}
                for key in ("generation_config", "safety_settings", "tools", "tool_config"):
                    if key in kwargs and kwargs[key] is not None:
                        gen_kwargs[key] = kwargs[key]
                resp = self._retry(self._model.generate_content, parts, **gen_kwargs)
                text = getattr(resp, "text", "") or ""
                meta = getattr(resp, "to_dict", lambda: {})()
                if text:
                    return {"text": text, "meta": meta, "tokens_in": 0, "tokens_out": 0, "cost": 0.0}
                # se torna vuoto, prova REST
            except Exception as e:
                # se è un 404/“Requested entity was not found”, usa REST
                if "Requested entity was not found" not in str(e) and "404" not in str(e):
                    # altri errori non-transienti: rilancia
                    raise

        # 2) fallback REST (replica la tua chiamata PowerShell)
        return self._retry(self._rest_generate, parts, **kwargs)

    def summarize_chunks(self, chunks, system_instruction=None, **kwargs):
        partial_summaries = []
        total = len(chunks) or 0
        for idx, chunk in enumerate(chunks, 1):
            prompt = (
                f"Riassumi concisamente il seguente testo (parte {idx}/{total}). "
                f"Mantieni numeri ed elementi utili alla valutazione deforestazione:\n\n{chunk}"
            )
            res = self.generate(prompt, system_instruction=system_instruction, **kwargs)
            partial_summaries.append(res["text"].strip())

        merged_prompt = (
            "Unisci i seguenti riassunti parziali in un unico executive summary con bullet point "
            "e una sezione 'Rischi/Anomalie'. Evita ripetizioni e mantieni i dati numerici:\n\n"
            + "\n\n".join([s for s in partial_summaries if s])
        )
        final = self.generate(merged_prompt, system_instruction=system_instruction, **kwargs)
        return final
