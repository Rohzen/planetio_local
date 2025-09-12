from odoo import models
import re, difflib

def _normalize(h):
    return re.sub(r"[^a-z0-9]+", " ", (h or "").lower()).strip()

class ExcelHeaderMatcher(models.AbstractModel):
    _name = "excel.header.matcher"
    _description = "Header Matcher"

    def match_headers(self, headers, tmpl_field):
        # alias esatti
        norm_headers = { _normalize(h): h for h in headers }
        for a in tmpl_field.alias_ids:
            na = _normalize(a.alias)
            if na in norm_headers:
                return {"header": norm_headers[na], "score": 0.99, "source": "alias"}

        # geo regex dedicati
        fname = (tmpl_field.field_id.name or "").lower()
        if "geo" in fname:
            # priorità a colonne che contengono “coordinate”, “lat/lon”
            for h in headers:
                if re.search(r"(?i)\bcoordinates?\b|\b(lat|lon|latitude|longitude)\b", h or ""):
                    return {"header": h, "score": 0.8, "source": "regex"}

        # fuzzy sul field_description (es. “Farmer Name”) e sul name (“farmer_name”)
        query = (tmpl_field.field_id.field_description or tmpl_field.field_id.name or "").replace("_", " ")
        best = difflib.get_close_matches(query, headers, n=1, cutoff=0.7)
        if best:
            score = difflib.SequenceMatcher(None, query.lower(), best[0].lower()).ratio()
            return {"header": best[0], "score": float(score), "source": "fuzzy"}

        return {"header": None, "score": 0.0, "source": "none"}
