import sys
import types
import importlib.util
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
