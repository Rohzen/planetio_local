from odoo import models
import json

_GEMINI_PARAM_KEY = "planetio_ai_import.gemini_api_key"
_GEMINI_MODEL_KEY = "planetio_ai_import.gemini_model"
_DEFAULT_MODEL = "gemini-1.5-pro"

PROMPT_TEMPLATE = """
You are a data-mapping assistant. You must map spreadsheet columns to target fields.
Return ONLY a JSON object with this shape:
{
  "mappings": [
    {"field": "<odoo_field_name>", "header": "<best matching header or null>", "score": 0.0-1.0, "reason": "<short>"}
  ]
}

Context:
- Headers (exact order): {headers}
- Sample rows (strings): {samples}
- Target fields with hints:
{targets}

Rules:
- If you are not confident for a field, set "header" to null and "score" <= 0.4.
- Prefer headers that are semantically closest, not banners (e.g. 'EUDR COMPLIANCE').
- Geo hints: 'geometry' expects either POINT (lat/lon) or POLYGON ('COORDINATES n' columns).
- Country/region/municipality/farmer_name/farm_name are text; area_ha is numeric.
- Return valid JSON only, no extra text.
"""

class ExcelLLMAgent(models.AbstractModel):
    _name = "excel.llm.agent"
    _description = "Gemini Mapping Agent"

    def _get_client(self):
        """Lazy import to avoid hard dependency if the key is missing."""
        api_key = self.env["ir.config_parameter"].sudo().get_param(_GEMINI_PARAM_KEY)
        if not api_key:
            return None, None
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            model_name = self.env["ir.config_parameter"].sudo().get_param(_GEMINI_MODEL_KEY, _DEFAULT_MODEL)
            model = genai.GenerativeModel(model_name)
            return genai, model
        except Exception:
            return None, None

    def suggest_mapping(self, headers, sample_rows, target_fields_meta):
        """
        headers: list[str]
        sample_rows: list[dict] (few preview rows)
        target_fields_meta: list[dict] with keys:
            field (technical), label (human), required (bool), transformer (str), aliases (list[str])
        returns: list[dict] -> [{"field","header","score","reason","source":"gemini"}]
        """
        genai, model = self._get_client()
        if not model:
            return []

        # prepare prompt
        targets = []
        for t in target_fields_meta:
            line = f"- {t.get('field')} (label='{t.get('label')}', required={bool(t.get('required'))}, transformer='{t.get('transformer')}', aliases={t.get('aliases', [])})"
            targets.append(line)

        # compact samples to strings (avoid leaking big payloads)
        samples_str = []
        for r in (sample_rows or [])[:3]:
            # keep only non-empty items
            compact = {k: ("" if v is None else str(v)) for k, v in r.items()}
            samples_str.append(compact)

        prompt = PROMPT_TEMPLATE.format(
            headers=json.dumps(headers, ensure_ascii=False),
            samples=json.dumps(samples_str, ensure_ascii=False),
            targets="\n".join(targets)
        )

        try:
            resp = model.generate_content(prompt)
            txt = resp.candidates[0].content.parts[0].text if resp and resp.candidates else ""
            # sometimes Gemini wraps in markdown code fences; strip them
            txt = txt.strip().strip("`").strip()
            # find first json-looking segment
            start = txt.find("{")
            end = txt.rfind("}")
            payload = json.loads(txt[start:end+1]) if start >= 0 and end >= 0 else {}
            mappings = payload.get("mappings", [])
        except Exception:
            mappings = []

        # normalize
        out = []
        for m in mappings:
            out.append({
                "field": m.get("field"),
                "header": m.get("header"),
                "score": float(m.get("score") or 0.0),
                "reason": m.get("reason") or "",
                "source": "gemini",
            })
        return out
