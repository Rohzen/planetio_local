import sys
import types
import importlib.util
import base64
import json
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.append(str(repo_root))

odoo = types.ModuleType('odoo')

class _Field:
    def __init__(self, *args, **kwargs):
        pass

odoo.models = types.SimpleNamespace(TransientModel=object)
odoo.fields = types.SimpleNamespace(Binary=_Field, Char=_Field, Many2one=_Field, Boolean=_Field, Selection=_Field, Text=_Field)
odoo.exceptions = types.SimpleNamespace(UserError=Exception)
odoo._ = lambda s: s
sys.modules['odoo'] = odoo
sys.modules['odoo.exceptions'] = odoo.exceptions

module_path = repo_root / 'planetio' / 'wizards' / 'import_wizard.py'
spec = importlib.util.spec_from_file_location('import_wizard', module_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_extract_geojson_features():
    data = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 2]}, "properties": {"name": "A"}},
            {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[0,0],[0,1],[1,1],[0,0]]]}, "properties": {}}
        ]
    }
    feats = mod.extract_geojson_features(data)
    assert len(feats) == 2
    assert feats[0][0]["type"] == "Point"
    assert feats[0][1]["name"] == "A"


def test_detect_geojson_without_extension():
    data = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]}, "properties": {}}
        ],
    }

    class DummyWizard(mod.ExcelImportWizard):
        def __init__(self, file_data, file_name=None):
            self.file_data = base64.b64encode(file_data)
            self.file_name = file_name
            self.env = {}
            self.id = 1

        def ensure_one(self):
            pass

    wiz = DummyWizard(json.dumps(data).encode("utf-8"), file_name="upload.bin")
    result = wiz.action_detect_and_map()
    assert wiz.step == "validate"
    preview = json.loads(wiz.preview_json)
    assert preview[0]["type"] == "Point"
    assert result["type"] == "ir.actions.act_window"


def test_map_geojson_properties_basic():
    props = {
        "farmer_s_name": "María Carmen Ramos",
        "id": "1203-1954-00029",
        "country": "Honduras ",
        "region": "La Paz",
        "municipality": "Cabañas",
        "area": 2.25,
        "name_of_farm": "CMP-007",
        "ha_total": 2.25,
        "type": "Punto",
        "latitude": 14.059475,
        "longitude": -88.12559,
        "sheet_name": "Lot 604",
    }
    vals, extras = mod.map_geojson_properties(props)
    assert vals["farmer_name"] == "María Carmen Ramos"
    assert vals["farmer_id_code"] == "1203-1954-00029"
    assert vals["country"].strip() == "Honduras"
    assert vals["region"] == "La Paz"
    assert vals["municipality"] == "Cabañas"
    assert vals["farm_name"] == "CMP-007"
    assert abs(vals["area_ha"] - 2.25) < 1e-6
    assert vals["geo_type_raw"] == "Punto"
    assert extras["latitude"] == 14.059475
    assert extras["sheet_name"] == "Lot 604"


def test_plot_id_equivalence():
    vals1, _ = mod.map_geojson_properties({"plot": "PLOT1"})
    vals2, _ = mod.map_geojson_properties({"plot-id": "PLOT2"})
    assert vals1["farmer_id_code"] == "PLOT1"
    assert vals2["farmer_id_code"] == "PLOT2"
