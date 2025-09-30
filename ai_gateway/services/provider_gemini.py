import time
import random
import json
import requests
import google.generativeai as genai


class GeminiProvider(object):
    # Prefer current, generally-available models
    PREFERRED_MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"]
    # v1beta → v1
    REST_BASE = "https://generativelanguage.googleapis.com/v1"

    # map old → new for compatibility
    _MODEL_COMPAT = {
        "gemini-1.5-pro": "gemini-2.5-pro",
        "gemini-1.5-flash": "gemini-2.5-flash",
        "gemini-1.5-flash-8b": "gemini-2.5-flash-lite",
        "gemini-1.5-pro-latest": "gemini-2.5-pro",
        "gemini-pro": "gemini-2.0-flash",  # legacy alias, best-effort
    }

    def __init__(self, env):
        self.env = env
        self.api_key = env['ir.config_parameter'].sudo().get_param('ai_gateway.gemini_api_key')
        raw_model = env['ir.config_parameter'].sudo().get_param(
            'ai_gateway.gemini_model', default=self.PREFERRED_MODELS[0]
        )
        if not self.api_key:
            raise ValueError("Gemini API key mancante in Impostazioni")

        # normalize and upgrade model id if needed
        target = self._normalize_to_bare_id(raw_model)
        self.model_name = self._MODEL_COMPAT.get(target, target)

        self._client_ok = False
        try:
            genai.configure(api_key=self.api_key)
            # If the installed client is modern enough, use it; else fall back to REST
            if hasattr(genai, "GenerativeModel"):
                self._model = genai.GenerativeModel(self.model_name)
                self._use_generate_text = False
                self._client_ok = True
            else:
                self._model = None
                self._use_generate_text = True
        except Exception:
            self._model = None
            self._use_generate_text = True

    # optional: call during __init__ after computing self.model_name, to auto-heal bad IDs
    def _maybe_select_available_model(self):
        try:
            import requests
            resp = requests.get(
                f"{self.REST_BASE}/models",
                params={"key": self.api_key},
                timeout=5,
            )
            resp.raise_for_status()
            available = {m["name"].split("/", 1)[-1] for m in resp.json().get("models", [])}
            if self.model_name not in available:
                for pref in self.PREFERRED_MODELS:
                    if pref in available:
                        self.model_name = pref
                        return
        except Exception:
            pass

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

    def _rest_model_candidates(self):
        model = self.model_name or self.PREFERRED_MODELS[0]
        model = model.split("@")[0]

        if "/" in model:
            return [model]

        candidates = []

        def add(name):
            if name and name not in candidates:
                candidates.append(name)

        add(model)

        base = model
        suffix = None
        for ending in ("-latest", "-003", "-002", "-001"):
            if base.endswith(ending):
                suffix = ending
                base = base[: -len(ending)]
                break

        if suffix == "-latest":
            add(base)
            add(f"{base}-001")
        elif suffix in {"-003", "-002", "-001"}:
            add(base)
            add(f"{base}-latest")
            if suffix != "-001":
                add(f"{base}-001")
        else:
            add(f"{base}-latest")
            add(f"{base}-001")

        for preferred in self.PREFERRED_MODELS:
            add(preferred)

        return candidates

    def _rest_generate(self, parts, **kwargs):
        payload = {"contents": [{"parts": [{"text": p} for p in parts]}]}
        # passa configurazioni opzionali se presenti (come da API)
        gen_cfg = kwargs.get("generation_config")
        if isinstance(gen_cfg, dict):
            payload.update(gen_cfg)
        safety = kwargs.get("safety_settings")
        if safety:
            payload["safetySettings"] = safety

        headers = {"Content-Type": "application/json"}
        last_error = None

        for candidate in self._rest_model_candidates():
            url = f"{self.REST_BASE}/models/{candidate}:generateContent?key={self.api_key}"
            resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=60)
            if resp.status_code == 404:
                last_error = RuntimeError(
                    f"Model '{candidate}' non trovato (REST 404). "
                    f"Controlla 'ai_gateway.gemini_model' oppure prova uno tra: "
                    f"{', '.join(self.PREFERRED_MODELS)}. Body: {resp.text}"
                )
                continue
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

            if candidate != self.model_name:
                self.model_name = candidate

            return {"text": text, "meta": data, "tokens_in": 0, "tokens_out": 0, "cost": 0.0}

        if last_error:
            raise last_error
        raise RuntimeError("AI request error: nessun modello REST disponibile")

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
            "Unisci i seguenti riassunti parziali in un unico executive summary con bullet point, "
            "aggiungi una sezione 'Rischi/Anomalie' e una sezione 'Azioni correttive' con interventi "
            "pratici e mirati. Evita ripetizioni e mantieni i dati numerici:\n\n"
            + "\n\n".join([s for s in partial_summaries if s])
        )
        final = self.generate(merged_prompt, system_instruction=system_instruction, **kwargs)
        return final
