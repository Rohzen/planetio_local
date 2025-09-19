import base64
import json
import types
import importlib.util
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.append(str(repo_root))


def _ensure_odoo_stubs():
    if 'odoo' not in sys.modules:
        odoo = types.ModuleType('odoo')
        sys.modules['odoo'] = odoo
    else:
        odoo = sys.modules['odoo']

    if not hasattr(odoo, 'models'):
        odoo.models = types.SimpleNamespace(TransientModel=object)
    if not hasattr(odoo, 'fields'):
        class _Field:
            def __init__(self, *args, **kwargs):
                pass

        odoo.fields = types.SimpleNamespace(
            Binary=_Field,
            Char=_Field,
            Many2one=_Field,
            Boolean=_Field,
            Selection=_Field,
            Text=_Field,
        )
    odoo.exceptions = types.SimpleNamespace(UserError=Exception)
    odoo._ = lambda s: s
    sys.modules.setdefault('odoo.exceptions', odoo.exceptions)


_ensure_odoo_stubs()

module_path = repo_root / 'planetio' / 'wizards' / 'import_wizard.py'
spec = importlib.util.spec_from_file_location('import_wizard_confirm', module_path)
wizard_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wizard_mod)


class DummyAttachmentModel:
    def __init__(self):
        self.created = []

    def create(self, vals):
        record = types.SimpleNamespace(id=len(self.created) + 1, **vals)
        self.created.append(record)
        return record


class DummyExcelService:
    def __init__(self):
        self.pick_calls = 0
        self.propose_calls = 0
        self.validate_calls = 0
        self.create_calls = 0

    def pick_best_sheet(self, job):
        self.pick_calls += 1
        return 'Sheet1', 100

    def propose_mapping(self, job):
        self.propose_calls += 1
        mapping = {'name': 'name', 'farmer_name': 'farmer_name'}
        preview = [{'name': 'Farm 1', 'farmer_name': 'Alice'}]
        return mapping, preview

    def transform_and_validate(self, job):
        self.validate_calls += 1
        payload = {
            'valid': [
                {
                    'name': 'Farm 1',
                    'farmer_name': 'Alice',
                    'geometry': 'GEOM',
                    'geo_type': 'point',
                }
            ],
            'errors': [],
        }
        return json.dumps(payload)

    def create_records(self, job):
        self.create_calls += 1
        return {'declaration_id': 42, 'created': 1}


class DummyEnv(dict):
    def __init__(self, **models):
        super().__init__(**models)
        self.context = {}

    def __getitem__(self, item):
        return super().__getitem__(item)


def test_action_confirm_runs_detection_and_validation_for_excel():
    attachment_model = DummyAttachmentModel()
    service = DummyExcelService()
    env = DummyEnv(
        **{
            'ir.attachment': attachment_model,
            'excel.import.service': service,
        }
    )

    class DummyWizard(wizard_mod.ExcelImportWizard):
        def __init__(self):
            self.file_name = 'upload.xlsx'
            self.file_data = base64.b64encode(b'test excel content')
            self.template_id = types.SimpleNamespace(id=1)
            self.debug_import = True
            self.step = 'upload'
            self.attachment_id = False
            self.sheet_name = False
            self.mapping_json = False
            self.preview_json = False
            self.result_json = False
            self.declaration_id = False
            self.env = env
            self.id = 1

        def ensure_one(self):
            pass

    wiz = DummyWizard()
    action = wiz.action_confirm()

    assert service.pick_calls == 1
    assert service.propose_calls == 1
    assert service.validate_calls == 1
    assert service.create_calls == 1

    assert wiz.step == 'confirm'
    assert json.loads(wiz.result_json)['valid'][0]['geometry'] == 'GEOM'
    assert action['res_model'] == 'eudr.declaration'
    assert action['res_id'] == 42
