import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest


repo_root = Path(__file__).resolve().parents[1]
sys.path.append(str(repo_root))


# Provide a minimal package structure so that relative imports succeed.
planetio_pkg = sys.modules.setdefault('planetio', types.ModuleType('planetio'))
setattr(planetio_pkg, '__path__', [str(repo_root / 'planetio')])
services_pkg = sys.modules.setdefault('planetio.services', types.ModuleType('planetio.services'))
adapter_mod = sys.modules.setdefault(
    'planetio.services.eudr_adapter_odoo',
    types.ModuleType('planetio.services.eudr_adapter_odoo'),
)


def _stub_action(*args, **kwargs):  # pragma: no cover - simple stub
    return None


setattr(adapter_mod, 'action_retrieve_dds_numbers', _stub_action)


class FakeConfigParameter:
    def sudo(self):
        return self

    def get_param(self, key, default=None):
        if key == 'planetio.eudr_point_area_ha':
            return '0.0004'
        return default


module_path = repo_root / 'planetio' / 'models' / 'eudr_models.py'
spec = importlib.util.spec_from_file_location('planetio.models.eudr_models', module_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


EUDRDeclaration = mod.EUDRDeclaration


def _make_line(geometry_dict):
    return types.SimpleNamespace(geometry=json.dumps(geometry_dict))


def _make_record(lines):
    rec = EUDRDeclaration()
    rec.line_ids = lines
    rec.area_ha = 0.0
    rec.env = {'ir.config_parameter': FakeConfigParameter()}
    return rec


def test_single_point_uses_four_square_meters():
    rec = _make_record([
        _make_line({"type": "Point", "coordinates": [0.0, 0.0]}),
    ])

    rec._compute_area_ha()

    assert rec.area_ha == pytest.approx(4.0 / 10000.0)


def test_polygon_and_point_are_summed():
    polygon = {
        "type": "Polygon",
        "coordinates": [
            [
                [0.0, 0.0],
                [0.001, 0.0],
                [0.001, 0.001],
                [0.0, 0.001],
                [0.0, 0.0],
            ]
        ],
    }

    polygon_record = _make_record([_make_line(polygon)])
    polygon_record._compute_area_ha()

    combined_record = _make_record([
        _make_line(polygon),
        _make_line({"type": "Point", "coordinates": [0.0, 0.0]}),
    ])
    combined_record._compute_area_ha()

    assert combined_record.area_ha > polygon_record.area_ha
    assert combined_record.area_ha == pytest.approx(
        polygon_record.area_ha + 4.0 / 10000.0,
        rel=1e-3,
    )
