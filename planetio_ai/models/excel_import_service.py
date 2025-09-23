import json
import re
from types import SimpleNamespace

from odoo import models


class ExcelImportServiceAI(models.AbstractModel):
    _inherit = "excel.import.service"

    def _propose_mapping_with_ai(self, headers, sample_rows):
        """Use the AI gateway to suggest a mapping based on spreadsheet headers."""

        icp = self.env["ir.config_parameter"].sudo()
        provider = icp.get_param("ai_gateway.default_provider", "gemini") or "gemini"

        instructions = (
            "You are assisting with mapping spreadsheet columns to Planetio EUDR fields. "
            "Allowed target fields are: name, farmer_name, farmer_id_code, tax_code, "
            "country, region, municipality, farm_name, area_ha, latitude, longitude, "
            "coordinates_1..coordinates_99 and geo_type_raw. "
            "Only include fields you can confidently map. Return a compact JSON object "
            "where each key is one of the allowed target fields and the value is the "
            "exact column header to use. Respond with valid JSON only."
        )

        payload = {
            "headers": headers,
            "sample_rows": sample_rows,
        }
        prompt = f"{instructions}\n\nInput:\n{json.dumps(payload, ensure_ascii=False)}"

        request = SimpleNamespace(
            provider=provider,
            task_type="chat",
            payload=prompt,
            attachment_ids=[],
        )

        result = self.env["ai.gateway.service"].run_request(request)
        response_text = (result or {}).get("text") or ""
        mapping = self._parse_ai_mapping_response(response_text)
        if not mapping:
            raise ValueError("AI did not return a usable mapping")
        return mapping

    def _parse_ai_mapping_response(self, text):
        cleaned = (text or "").strip()
        if not cleaned:
            return {}

        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.I).strip()
            if cleaned.endswith("```"):
                cleaned = cleaned[: -3].strip()

        try:
            candidate = json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, re.S)
            if not match:
                raise
            candidate = json.loads(match.group(0))

        if not isinstance(candidate, dict):
            return {}

        allowed = {
            "name",
            "farmer_name",
            "farmer_id_code",
            "tax_code",
            "country",
            "region",
            "municipality",
            "farm_name",
            "area_ha",
            "latitude",
            "longitude",
            "geo_type_raw",
        }

        mapping = {}
        for key, value in candidate.items():
            if not isinstance(key, str) or not isinstance(value, str):
                continue
            normalized_key = key.strip().lower()
            if normalized_key in allowed or re.match(r"coordinates_\d+\Z", normalized_key):
                mapping[normalized_key] = value.strip()

        return mapping
