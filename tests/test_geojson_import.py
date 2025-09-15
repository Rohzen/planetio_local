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
