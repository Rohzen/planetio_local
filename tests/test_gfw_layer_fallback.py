import sys
import types
from pathlib import Path


repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))


if 'odoo' not in sys.modules:
    odoo = types.ModuleType('odoo')
    sys.modules['odoo'] = odoo
else:
    odoo = sys.modules['odoo']

models_ns = getattr(odoo, 'models', types.SimpleNamespace())
for attr in ('Model', 'AbstractModel', 'TransientModel'):
    if not hasattr(models_ns, attr):
        setattr(models_ns, attr, object)
odoo.models = models_ns

api_ns = getattr(odoo, 'api', types.SimpleNamespace())
if not hasattr(api_ns, 'onchange'):
    api_ns.onchange = lambda *args, **kwargs: (lambda func: func)
if not hasattr(api_ns, 'model'):  # used as decorator elsewhere
    api_ns.model = lambda func: func
odoo.api = api_ns

if not hasattr(odoo, '_'):
    odoo._ = lambda value: value

fields_ns = getattr(odoo, 'fields', types.SimpleNamespace())

class _Field:
    def __init__(self, *args, **kwargs):
        pass

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

tools_module = sys.modules.get('odoo.tools')
if tools_module is None:
    tools_module = types.ModuleType('odoo.tools')
    sys.modules['odoo.tools'] = tools_module
if not hasattr(tools_module, 'ustr'):
    tools_module.ustr = lambda value: str(value)
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

modules_pkg = sys.modules.get('odoo.modules')
if modules_pkg is None:
    modules_pkg = types.ModuleType('odoo.modules')
    sys.modules['odoo.modules'] = modules_pkg
module_subpkg = getattr(modules_pkg, 'module', None)
if module_subpkg is None:
    module_subpkg = types.ModuleType('odoo.modules.module')
    modules_pkg.module = module_subpkg
    sys.modules['odoo.modules.module'] = module_subpkg
if not hasattr(module_subpkg, 'get_module_resource'):
    module_subpkg.get_module_resource = lambda *args, **kwargs: ''


from planetio.services.api.gfw_deforestation import DeforestationProviderGFW
from odoo.exceptions import UserError


class DummyICP:
    def sudo(self):
        return self

    def get_param(self, key):
        if key == 'planetio.gfw_api_origin':
            return 'http://localhost'
        if key == 'planetio.gfw_alert_years':
            return None
        if key == 'planetio.gfw_days_back':
            return '365'
        return ''


class DummyEnv(dict):
    def __getitem__(self, key):
        return super().__getitem__(key)


class DummyProvider(DeforestationProviderGFW):
    def __init__(self):
        self.env = DummyEnv({'ir.config_parameter': DummyICP()})
        self._sql_calls = []

    def check_prerequisites(self):
        return True

    def _get_api_key(self):
        return 'dummy-key'

    def _prepare_headers(self, origin, api_key):
        return {}

    def _gfw_execute_sql(self, headers, geometry, sql_template, date_from, allow_short=True):
        self._sql_calls.append(sql_template)
        if 'SUM(alert__count)' in sql_template:
            raise UserError('Provider gfw: Richiesta rifiutata da GFW: {"status":"failed","message":"Layer alerts__count is invalid"}')
        if 'LIMIT 365' in sql_template:
            return ({'data': [{'alert_date': date_from, 'alert_count': 3, 'area_ha': 0.5}]},
                    {'endpoint': 'latest', 'date_from': date_from, 'sql': sql_template, 'status_code': 200})
        if 'LIMIT 200' in sql_template:
            return ({'data': [{'alert_date': date_from, 'alert_count': 2, 'area_ha': 0.2, 'confidence': 'high'}]},
                    {'endpoint': 'latest', 'date_from': date_from, 'sql': sql_template, 'status_code': 200})
        return ({'data': [{'alert_count': 5, 'area_ha_total': 1.25, 'first_alert_date': date_from, 'last_alert_date': date_from}]},
                {'endpoint': 'latest', 'date_from': date_from, 'sql': sql_template, 'status_code': 200})


class DummyLine:
    display_name = 'Dummy line'

    def _line_geometry(self):
        return {
            'type': 'Polygon',
            'coordinates': [[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]]],
        }


def test_analyze_line_uses_plural_layer_fallback():
    provider = DummyProvider()
    result = provider.analyze_line(DummyLine())

    assert result['meta']['field_variant']['count'] == 'alerts__count'
    # the first SQL should have used the singular field before falling back
    assert any('SUM(alert__count)' in sql for sql in provider._sql_calls)
    assert any('SUM(alerts__count)' in sql for sql in provider._sql_calls)
    assert result['metrics']['alert_count'] == 5
    assert result['metrics']['area_ha_total'] == 1.25
