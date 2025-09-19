import sys
import types


odoo = sys.modules.setdefault('odoo', types.ModuleType('odoo'))


class _Model:
    def __init__(self, *args, **kwargs):  # pragma: no cover - simple stub
        pass

    def __iter__(self):  # pragma: no cover - allows "for rec in self"
        return iter([self])


class _Field:
    def __init__(self, *args, **kwargs):  # pragma: no cover - simple stub
        pass


class _DatetimeField(_Field):
    @staticmethod
    def now():  # pragma: no cover - deterministic stub
        return None


models = getattr(odoo, 'models', types.SimpleNamespace())
models.Model = getattr(models, 'Model', _Model)
models.AbstractModel = getattr(models, 'AbstractModel', _Model)
models.TransientModel = getattr(models, 'TransientModel', _Model)
odoo.models = models


fields = getattr(odoo, 'fields', types.SimpleNamespace())
for name, value in {
    'Binary': _Field,
    'Boolean': _Field,
    'Char': _Field,
    'Datetime': _DatetimeField,
    'Float': _Field,
    'Integer': _Field,
    'Many2one': _Field,
    'One2many': _Field,
    'Selection': _Field,
    'Text': _Field,
}.items():
    if not hasattr(fields, name):
        setattr(fields, name, value)
odoo.fields = fields


def _depends(*args, **kwargs):  # pragma: no cover - simple decorator stub
    def decorator(func):
        return func

    return decorator


api = getattr(odoo, 'api', types.SimpleNamespace())
api.depends = getattr(api, 'depends', _depends)
api.model_create_multi = getattr(api, 'model_create_multi', lambda func: func)
api.model = getattr(api, 'model', lambda func: func)
odoo.api = api


if not hasattr(odoo, '_'):
    odoo._ = lambda s: s


exceptions = types.ModuleType('odoo.exceptions')
setattr(exceptions, 'UserError', Exception)
sys.modules['odoo.exceptions'] = exceptions
odoo.exceptions = exceptions
