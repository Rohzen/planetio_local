import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest


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


def test_extract_alerts_from_summary_payload():
    payload = {
        "risk_level": "elevated",
        "primary_drivers": ["smallholder clearing", "selective logging"],
        "gfw_layer": "GLAD-L + GLAD-S2 (optical)",
        "state": "Amazonas",
        "source": "Global Forest Watch",
        "alert_count_30d": 271,
        "notes": "Northern AOI with intermittent alert pockets; watch mining pressure regionally.",
        "period": "2025-08-01 to 2025-09-21",
        "confidence": "lower (intermittent signal)",
        "last_alert_date": "2025-09-15",
    }

    status = mod.parse_deforestation_external_properties(payload)
    assert status is not None

    line = mod.EUDRDeclarationLineDeforestation()
    line.id = 123

    alerts = line._extract_alerts_from_payload(status)
    assert isinstance(alerts, list)
    assert len(alerts) == 1

    alert = alerts[0]
    assert alert["risk_level"] == "elevated"
    assert alert["alert_count"] == 271
    assert alert["last_alert_date"] == "2025-09-15"

    provider = (status.get("meta") or {}).get("provider")
    vals = line._prepare_alert_vals(alert, provider)
    assert vals["line_id"] == 123
    assert vals["provider"] == "gfw"
    assert vals["risk_level"] == "elevated"
    assert vals["alert_date_raw"] == "2025-09-15"
    assert vals["area_ha"] == 0.0


def test_prepare_alert_vals_area_from_total_key():
    line = mod.EUDRDeclarationLineDeforestation()
    line.id = 456

    alert = {
        "id": "alert-123",
        "area_ha_total": "1.75",
        "alert_date": "2025-02-10",
    }

    vals = line._prepare_alert_vals(alert, provider="gfw")

    assert vals["line_id"] == 456
    assert vals["provider"] == "gfw"
    assert vals["area_ha"] == pytest.approx(1.75)
