import os
import types
import sys
import importlib.util
from pathlib import Path

# Ensure repository root is on sys.path for module loading
repo_root = Path(__file__).resolve().parents[1]
sys.path.append(str(repo_root))

# Stub minimal odoo package
odoo = types.ModuleType('odoo')
odoo.models = types.SimpleNamespace(AbstractModel=object)
sys.modules.setdefault('odoo', odoo)

# Load module directly to avoid importing other Odoo-dependent modules
module_path = repo_root / 'planetio' / 'models' / 'excel_transformers.py'
spec = importlib.util.spec_from_file_location('excel_transformers', module_path)
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)

def test_parse_pair_decimal():
    lat, lon = t._parse_pair('45.0, 9.0')
    assert lat == 45.0 and lon == 9.0

def test_parse_pair_invalid():
    lat, lon = t._parse_pair('foo')
    assert lat is None and lon is None
