import importlib.util
import json
import sys
import types
from pathlib import Path


repo_root = Path(__file__).resolve().parents[1]


def _ensure_odoo_stub():
    odoo = sys.modules.get('odoo')
    if odoo is None:
        odoo = types.ModuleType('odoo')
        sys.modules['odoo'] = odoo

    models_ns = getattr(odoo, 'models', types.SimpleNamespace())
    for attr in ('Model', 'AbstractModel', 'TransientModel'):
        if not hasattr(models_ns, attr):
            setattr(models_ns, attr, object)
    odoo.models = models_ns

    class _Field:
        def __init__(self, *args, **kwargs):
            pass

    fields_ns = getattr(odoo, 'fields', types.SimpleNamespace())
    for attr in (
        'Binary',
        'Char',
        'Integer',
        'Float',
        'Text',
        'Boolean',
        'Many2one',
        'One2many',
        'Date',
        'Selection',
    ):
        setattr(fields_ns, attr, _Field)
    odoo.fields = fields_ns

    if not hasattr(odoo, 'api'):
        odoo.api = types.SimpleNamespace()

    odoo._ = lambda value: value

    tools_module = sys.modules.get('odoo.tools')
    if tools_module is None:
        tools_module = types.ModuleType('odoo.tools')
        sys.modules['odoo.tools'] = tools_module
    if not hasattr(tools_module, 'ustr'):
        tools_module.ustr = lambda value: str(value)
    if not hasattr(tools_module, 'html_escape'):
        tools_module.html_escape = lambda value: value

    misc_module = sys.modules.get('odoo.tools.misc')
    if misc_module is None:
        misc_module = types.ModuleType('odoo.tools.misc')
        sys.modules['odoo.tools.misc'] = misc_module
    if not hasattr(misc_module, 'formatLang'):
        misc_module.formatLang = lambda env, value, digits=None: value

    tools_module.misc = misc_module
    odoo.tools = tools_module

    exceptions_mod = sys.modules.get('odoo.exceptions')
    if exceptions_mod is None:
        exceptions_mod = types.SimpleNamespace(UserError=Exception)
        sys.modules['odoo.exceptions'] = exceptions_mod
    if not hasattr(exceptions_mod, 'UserError'):
        exceptions_mod.UserError = Exception
    odoo.exceptions = exceptions_mod


_ensure_odoo_stub()

module_path = repo_root / 'planetio' / 'models' / 'eudr_deforestation.py'
spec = importlib.util.spec_from_file_location('eudr_deforestation', module_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_parse_external_properties_high_risk():
    props = {
        "last_alert_date": "2025-09-20",
        "source": "Global Forest Watch",
        "period": "2025-08-01 to 2025-09-21",
        "alert_count_30d": 1820,
        "risk_level": "high",
        "notes": "Fishbone side roads",
    }

    status = mod.parse_deforestation_external_properties(props)
    assert status is not None
    assert status['metrics']['alert_count'] == 1820
    assert status['metrics']['alert_count_30d'] == 1820
    assert status['meta']['risk_level'] == 'high'
    assert status['meta']['risk_flag'] is True
    assert status['meta']['source'] == "Global Forest Watch"
    assert "risk: high" in status['message']


def test_parse_external_properties_medium_risk_from_string():
    props = {
        "source": "GFW",
        "risk_level": "medium",
        "period": "2025-05-01 to 2025-05-31",
    }

    status = mod.parse_deforestation_external_properties(json.dumps(props))
    assert status is not None
    assert status['metrics']['alert_count'] == 0
    assert status['meta']['risk_level'] == 'medium'
    assert status['meta']['risk_flag'] is True
    assert "period" in status['message']


def test_parse_external_properties_no_signal():
    assert mod.parse_deforestation_external_properties({"foo": "bar"}) is None
