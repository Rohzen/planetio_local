import importlib.util
import sys
from pathlib import Path

import pytest


repo_root = Path(__file__).resolve().parents[1]
sys.path.append(str(repo_root))

module_path = repo_root / "planetio" / "utils" / "geo.py"
spec = importlib.util.spec_from_file_location("planetio.utils.geo", module_path)
geo_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(geo_mod)

estimate_geojson_area_ha = geo_mod.estimate_geojson_area_ha


class _FakeICP:
    def __init__(self, value):
        self._value = value

    def sudo(self):
        return self

    def get_param(self, key, default=None):  # pragma: no cover - simple helper
        if key == "planetio.gfw_min_area_ha":
            return str(self._value)
        return default


class _FakeEnv(dict):
    def __init__(self, value):
        super().__init__()
        self["ir.config_parameter"] = _FakeICP(value)


def test_point_uses_configured_minimum_area():
    env = _FakeEnv(5.5)
    geom = {"type": "Point", "coordinates": [12.0, 41.0]}

    area = estimate_geojson_area_ha(env, geom)

    assert area == pytest.approx(5.5)


def test_polygon_area_estimation():
    geom = {
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

    area = estimate_geojson_area_ha(None, geom, min_point_area_ha=4.0)

    # Roughly 1.24 ha at the equator. Allow generous tolerance for projection fallback.
    assert area == pytest.approx(1.24, rel=0.2)


def test_multipoint_accumulates_area():
    geom = {
        "type": "MultiPoint",
        "coordinates": [[0.0, 0.0], [0.5, 0.5], [1.0, 1.0]],
    }

    area = estimate_geojson_area_ha(None, geom, min_point_area_ha=2.0)

    assert area == pytest.approx(6.0)
