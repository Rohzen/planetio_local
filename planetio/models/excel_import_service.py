from odoo import models, api, _
import base64, io, json, re, os
import json as _json

try:
    import pandas as pd
except Exception:
    pd = None

try:  # pragma: no cover - fallback for standalone test loading
    from ..utils import estimate_geojson_area_ha
except ImportError:  # pragma: no cover - loaded outside package context
    import importlib.util
    from pathlib import Path

    _geo_path = Path(__file__).resolve().parents[1] / "utils" / "geo.py"
    _geo_spec = importlib.util.spec_from_file_location("planetio.utils.geo", _geo_path)
    _geo_mod = importlib.util.module_from_spec(_geo_spec)
    assert _geo_spec and _geo_spec.loader
    _geo_spec.loader.exec_module(_geo_mod)
    estimate_geojson_area_ha = _geo_mod.estimate_geojson_area_ha


class ExcelImportService(models.AbstractModel):
    _name = "excel.import.service"
    _description = "Excel Import Service (EUDR-aware)"

    def _extract_rows(self, job):
        """
        Prefer validated rows; fallback to preview; fallback to on-the-fly validation.
        Returns list of dicts.
        """
        rows = None
        # Prefer validated
        if getattr(job, "result_json", None):
            try:
                obj = job.result_json
                if isinstance(obj, str):
                    obj = _json.loads(obj)
                if isinstance(obj, dict) and "valid" in obj:
                    rows = obj["valid"]
                elif isinstance(obj, list):
                    rows = obj
            except Exception:
                rows = None
        # Fallback to preview
        if rows is None and getattr(job, "preview_json", None):
            try:
                obj = job.preview_json
                if isinstance(obj, str):
                    obj = _json.loads(obj)
                if isinstance(obj, list):
                    rows = obj
                elif isinstance(obj, dict) and "preview_rows" in obj:
                    rows = obj["preview_rows"]
            except Exception:
                rows = None
        # Final fallback: validate now
        if rows is None:
            try:
                rows = self.validate_rows(job).get("valid", [])
            except Exception:
                rows = []

        # Normalize to list[dict]
        safe_rows = []
        for r in rows or []:
            if isinstance(r, str):
                try:
                    r = _json.loads(r)
                except Exception:
                    continue
            if isinstance(r, dict):
                safe_rows.append(r)
        return safe_rows

    def create_records(self, job):
        """Create a declaration and related lines from the prepared rows."""
        rows = self._extract_rows(job)
        if not rows:
            return {"declaration_id": False, "created": 0}

        ctx = (self.env.context or {})
        Decl = self.env["eudr.declaration"]
        Line = self.env["eudr.declaration.line"]

        params = ctx.get('params') or {}
        model_context = params.get('model') or ctx.get('active_model')
        declaration_id = params.get('id') or ctx.get('active_id') or (ctx.get('active_ids') or [None])[0]

        decl = getattr(job, 'declaration_id', False)

        if not decl and model_context == "eudr.declaration" and declaration_id:
            decl = Decl.browse(declaration_id)

        # if not decl:
        #     decl = Decl.create({})

        if hasattr(job, "write"):
            try:
                job.sudo().write({"declaration_id": decl.id})
            except Exception:
                try:
                    job.declaration_id = decl.id
                except Exception:
                    pass

        base_name = (getattr(getattr(job, "attachment_id", None), "name", None) or "EUDR Import").rsplit(".", 1)[0]

        count = 0
        for idx, r in enumerate(rows, start=1):
            if not any(v for v in r.values() if v not in (None, "", [], {})):
                continue
            r.pop("geo_type", None)
            line_name = (
                r.get("name")
                or r.get("farm_name")
                or r.get("farmer_name")
                or f"{base_name} - row {idx}"
            )
            vals = dict(r)
            vals.update({
                "declaration_id": decl.id,
                "name": line_name,
                "external_uid": f"row{idx}",
            })
            Line.create(vals)
            count += 1

        return {"declaration_id": decl.id, "created": count}


    @api.model
    def pick_best_sheet(self, job):
        if pd is None:
            raise ValueError("pandas is required to import Excel files")
        content = base64.b64decode(job.attachment_id.datas)
        xls = pd.ExcelFile(io.BytesIO(content))
        tokens = ["latitude", "longitude", "coordinates", "farmer", "farmer's name", "id", "tax code",
                  "country", "region", "municipality", "name of farm", "ha total", "area", "type", "x", "y"]
        best = (None, -1)
        for s in xls.sheet_names:
            try:
                df = xls.parse(s, dtype=str, nrows=5)
            except Exception:
                continue
            cols = [str(c or '').lower() for c in df.columns]
            first_row = [str(v or '').lower() for v in (list(df.iloc[0]) if len(df.index) else [])]
            hit_cols = sum(any(t in c for c in cols) for t in tokens)
            hit_row = sum(any(t in c for c in first_row) for t in tokens)
            non_empty = int(df.dropna(how='all').shape[0] > 0 and df.dropna(axis=1, how='all').shape[1] > 0)
            unnamed_ratio = (sum(c.startswith('unnamed') for c in cols) / max(1, len(cols)))
            penalty = int(unnamed_ratio > 0.7)
            score = hit_cols * 3 + hit_row * 2 + non_empty * 5 - penalty
            if score > best[1]:
                best = (s, score)
        if best[0] is None:
            for s in xls.sheet_names:
                try:
                    df = xls.parse(s, dtype=str, nrows=1)
                except Exception:
                    continue
                if df.dropna(how='all').shape[0] > 0 and df.dropna(axis=1, how='all').shape[1] > 0:
                    return s, 0
            raise ValueError('No non-empty sheets found')
        return best

    @api.model
    def propose_mapping(self, job):
        df, sheet_name = self._load_normalized_dataframe(job.attachment_id, getattr(job, 'sheet_name', None))
        headers = list(df.columns)
        mapping = self._propose_mapping_from_headers(job.template_id, headers)
        if self._is_mapping_poor(mapping):
            ai_mapper = getattr(self, '_propose_mapping_with_ai', None)
            if callable(ai_mapper):
                try:
                    mapping = ai_mapper(headers, df.head(5).to_dict(orient='records'))
                    mapping['_source'] = 'ai'
                except Exception as e:
                    self._log(job, f'AI mapping failed: {e}')
        preview = df.head(20).to_dict(orient='records')
        return mapping, preview

    @api.model
    def transform_and_validate(self, job):
        """
        Shim for Odoo14 wizard: returns a JSON string with validation results.
        """
        result = self.validate_rows(job)
        return json.dumps(result, ensure_ascii=False, indent=2)

    @api.model
    def validate_rows(self, job):
        df, _ = self._load_normalized_dataframe(job.attachment_id, getattr(job, 'sheet_name', None))
        mapping = json.loads(job.mapping_json or '{}')
        ok_rows, errors = [], []
        for i, row in df.iterrows():
            try:
                normalized = self._normalize_row(row, mapping)
                if not normalized.get('geometry'):
                    raise ValueError('Missing geometry')
                ok_rows.append(normalized)
            except Exception as e:
                errors.append({'row': i + 1, 'error': str(e)})
        return {'valid': ok_rows, 'errors': errors}

    def _load_normalized_dataframe(self, attachment, preferred_sheet=None):
        if pd is None:
            raise ValueError('pandas is required to import Excel files')
        content = base64.b64decode(attachment.datas)
        xls = pd.ExcelFile(io.BytesIO(content))
        sheet_name, df = None, None
        if preferred_sheet and preferred_sheet in xls.sheet_names:
            tmp = xls.parse(preferred_sheet, dtype=str)
            if tmp.dropna(how='all').shape[0] > 0 and tmp.dropna(axis=1, how='all').shape[1] > 0:
                sheet_name, df = preferred_sheet, tmp
        if df is None:
            for s in xls.sheet_names:
                tmp = xls.parse(s, dtype=str)
                if tmp.dropna(how='all').shape[0] > 0 and tmp.dropna(axis=1, how='all').shape[1] > 0:
                    sheet_name, df = s, tmp
                    break
        if df is None:
            raise ValueError('No non-empty sheets found')

        unnamed_ratio = sum(str(c).startswith('Unnamed') for c in df.columns) / max(1, len(df.columns))
        first_row = [str(x) for x in list(df.iloc[0].astype(str).fillna(''))] if len(df.index) else []
        header_tokens = ['FARMER', 'LATITUDE', 'LONGITUDE', 'TYPE', 'COUNTRY', 'REGION', 'MUNICIPALITY', 'NAME OF FARM',
                         'HA', 'COORDINATES', 'X', 'Y']
        first_row_hits = sum(any(t in cell.upper() for t in header_tokens) for cell in first_row)
        if unnamed_ratio > 0.3 and first_row_hits >= 2:
            df.columns = [str(x).strip() for x in first_row]
            df = df.iloc[1:].reset_index(drop=True)

        df = df.dropna(axis=1, how='all').dropna(how='all')
        df = df.applymap(lambda v: v.strip() if isinstance(v, str) else v)
        df.columns = [self._standardize_header(h) for h in df.columns]
        return df, sheet_name

    def _standardize_header(self, h):
        h = re.sub(r'\s+', ' ', str(h or '')).strip().lower()
        repl = {
            "farmer's name *": 'farmer_name',
            "farmer's name": 'farmer_name',
            'farmer name': 'farmer_name',
            'id': 'farmer_id_code',
            'tax code': 'tax_code',
            'country*': 'country',
            'country* ': 'country',
            'country': 'country',
            'region': 'region',
            'municipality': 'municipality',
            'name of farm': 'farm_name',
            'ha total *': 'area_ha',
            'ha total': 'area_ha',
            'area': 'area_ha',
            'type *': 'geo_type_raw',
            'type': 'geo_type_raw',
            'latitude': 'latitude',
            'longitude': 'longitude',
            'x': 'x',
            'y': 'y',
        }
        if h in repl:
            return repl[h]
        m = re.match(r'coordinates\s*(\d+)', h, re.I)
        if m:
            return f'coordinates_{m.group(1)}'
        return h

    def _propose_mapping_from_headers(self, template, headers):
        mapping = {
            'name': self._best_header(headers, ['farmer_name', 'farm_name']),
            'farmer_name': self._best_header(headers, ['farmer_name']),
            'farmer_id_code': self._best_header(headers, ['farmer_id_code', 'id', 'farmer id']),
            'tax_code': self._best_header(headers, ['tax_code']),
            'country': self._best_header(headers, ['country']),
            'region': self._best_header(headers, ['region']),
            'municipality': self._best_header(headers, ['municipality']),
            'farm_name': self._best_header(headers, ['farm_name']),
            'area_ha': self._best_header(headers, ['area_ha']),
            'geo_type_raw': self._best_header(headers, ['geo_type_raw']),
        }
        return mapping

    def _best_header(self, headers, candidates):
        for c in candidates:
            for h in headers:
                if c == h:
                    return h
        for c in candidates:
            for h in headers:
                if c in h:
                    return h
        return None

    def _is_mapping_poor(self, mapping):
        core = ['farmer_name', 'country', 'farm_name']
        return sum(1 for c in core if mapping.get(c)) <= 1

    # def _ai_enabled(self):
    #     icp = self.env['ir.config_parameter'].sudo()
    #     enabled = icp.get_param('planetio.enable_ai_mapping', default='True')
    #     return str(enabled).lower() in ('1', 'true', 'yes', 'y')
    #
    # def _propose_mapping_with_ai(self, headers, sample_rows):
    #     try:
    #         import google.generativeai as genai
    #     except Exception as e:
    #         raise RuntimeError('Gemini SDK not installed') from e
    #     api_key = os.getenv('GEMINI_API_KEY')
    #     if not api_key:
    #         raise RuntimeError('GEMINI_API_KEY not configured')
    #     genai.configure(api_key=api_key)
    #     system = ('You are a data-mapping assistant. Given spreadsheet headers and sample rows, '
    #               'map each column to one of these EUDR fields when applicable: '
    #               'name, farmer_name, farmer_id_code, tax_code, country, region, municipality, farm_name, area_ha, '
    #               'latitude, longitude, coordinates_1..coordinates_99, geo_type_raw. '
    #               'Return a compact JSON object mapping EUDR field names to header strings. '
    #               'Only include fields you can map with high confidence.')
    #     prompt = {'headers': headers, 'sample_rows': sample_rows}
    #     model = genai.GenerativeModel('gemini-1.5-flash')
    #     resp = model.generate_content([system, json.dumps(prompt)])
    #     text = resp.text or ''
    #     m = re.search(r'\{.*\}', text, re.S)
    #     if not m:
    #         raise RuntimeError('Gemini did not return JSON mapping')
    #     mapping = json.loads(m.group(0))
    #     return mapping

    def _normalize_row(self, row, mapping):
        vals = {}
        for k in ['name', 'farmer_name', 'farmer_id_code', 'tax_code', 'country', 'region', 'municipality',
                  'farm_name']:
            col = mapping.get(k)
            if col and col in row:
                vals[k] = (row[col] or '').strip()
        col_area = mapping.get('area_ha')
        if col_area and col_area in row and str(row[col_area]).strip() != '':
            try:
                vals['area_ha'] = float(str(row[col_area]).replace(',', '.'))
            except Exception:
                pass

        lat_col = mapping.get('latitude') or self._guess_header(row.index, ['latitude', 'lat'])
        lon_col = mapping.get('longitude') or self._guess_header(row.index, ['longitude', 'lon'])
        geo_type_raw = (row.get(mapping.get('geo_type_raw')) if mapping.get('geo_type_raw') else None) or ''
        if geo_type_raw:
            vals['geo_type_raw'] = str(geo_type_raw)

        coords_cols = [c for c in row.index if str(c).startswith('coordinates_')]
        coords_pairs = []
        for c in sorted(coords_cols, key=lambda x: int(re.findall(r'\d+', x)[0])):
            try:
                lat_val = row[c]
                idx = list(row.index).index(c)
                lon_val = row[list(row.index)[idx + 1]] if idx + 1 < len(row.index) else None
                if self._is_number(lat_val) and self._is_number(lon_val):
                    coords_pairs.append([float(lon_val), float(lat_val)])
            except Exception:
                continue

        # Attempt to detect polygons encoded in a single cell
        polygon_pairs = None
        for val in row.values:
            parsed = self._parse_polygon_string(val)
            if parsed:
                polygon_pairs = parsed
                break

        geometry, geo_type = None, None
        if polygon_pairs:
            if polygon_pairs[0] != polygon_pairs[-1]:
                polygon_pairs.append(polygon_pairs[0])
            geometry = json.dumps({'type': 'Polygon', 'coordinates': [polygon_pairs]})
            geo_type = 'polygon'
        elif self._is_number(row.get(lat_col)) and self._is_number(row.get(lon_col)):
            lat = float(str(row.get(lat_col)).replace(',', '.'))
            lon = float(str(row.get(lon_col)).replace(',', '.'))
            geometry = json.dumps({'type': 'Point', 'coordinates': [lon, lat]})
            geo_type = 'point'
        elif coords_pairs:
            if coords_pairs and coords_pairs[0] != coords_pairs[-1]:
                coords_pairs.append(coords_pairs[0])
            geometry = json.dumps({'type': 'Polygon', 'coordinates': [coords_pairs]})
            geo_type = 'polygon'
        else:
            x_col = self._guess_header(row.index, ['x'])
            y_col = self._guess_header(row.index, ['y'])
            if self._is_number(row.get(y_col)) and self._is_number(row.get(x_col)):
                geometry = json.dumps({'type': 'Point', 'coordinates': [float(row.get(x_col)), float(row.get(y_col))]})
                geo_type = 'point'

        if not geo_type and geo_type_raw:
            t = str(geo_type_raw).strip().lower()
            if 'punt' in t:
                geo_type = 'point'
            elif 'pol' in t:
                geo_type = 'polygon'

        vals['geo_type'] = geo_type
        vals['geometry'] = geometry

        if geometry and not vals.get('area_ha'):
            computed_area = estimate_geojson_area_ha(self.env, geometry)
            if computed_area:
                vals['area_ha'] = computed_area
        return vals

    def _guess_header(self, headers, candidates):
        for c in candidates:
            for h in headers:
                if c == h or c in str(h):
                    return h
        return None

    def _is_number(self, v):
        try:
            if v is None: return False
            s = str(v).strip()
            if s == '': return False
            float(s.replace(',', '.'))
            return True
        except Exception:
            return False

    def _parse_polygon_string(self, val):
        """Extract polygon coordinates from a cell value.
        The value may contain pairs like "(lat, lon)" repeated. Returns a list of
        [lon, lat] pairs if at least three valid pairs are found, otherwise None."""
        if not isinstance(val, str):
            return None
        pairs = re.findall(r'(-?\d+(?:[\.,]\d+)?)\s*[;,]\s*(-?\d+(?:[\.,]\d+)?)', val)
        coords = []
        for a, b in pairs:
            try:
                lat = float(a.replace(',', '.'))
                lon = float(b.replace(',', '.'))
                coords.append([lon, lat])
            except Exception:
                continue
        if len(coords) >= 3:
            return coords
        return None

    def _log(self, job, msg):
        try:
            job.log_info(msg)
        except Exception:
            pass




