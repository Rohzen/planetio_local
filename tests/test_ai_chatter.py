import sys
import types
import importlib.util
from pathlib import Path

# Ensure repo root on path
repo_root = Path(__file__).resolve().parents[1]
sys.path.append(str(repo_root))

# Stub minimal odoo package for import
odoo = types.ModuleType('odoo')
odoo.api = types.SimpleNamespace()
odoo.fields = types.SimpleNamespace()
odoo.models = types.SimpleNamespace(Model=object, AbstractModel=object)
sys.modules.setdefault('odoo', odoo)

module_path = repo_root / 'planetio_ai' / 'wizard' / 'summarize_documents_wizard.py'
spec = importlib.util.spec_from_file_location('summ_wizard', module_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class DummyAttachments:
    def __init__(self, ids):
        self.ids = ids

class FakeAiRequest:
    def __init__(self):
        self.status = 'error'
        self.error_message = 'boom'
        self.response_text = ''
    def run_now(self):
        pass

class FakeAiRequestModel:
    def create(self, vals):
        return FakeAiRequest()

class FakeEnv(dict):
    pass

class FakeAttachmentModel:
    def create(self, vals):
        return vals


class FakeConfigParameter:
    def sudo(self):
        return self

    def get_param(self, key, default=None):
        return default

class FakeDeclaration(mod.PlanetioSummarizeWizard):
    def __init__(self):
        self.env = FakeEnv({
            'ai.request': FakeAiRequestModel(),
            'ir.attachment': FakeAttachmentModel(),
            'ir.config_parameter': FakeConfigParameter(),
        })
        self.attachment_ids = DummyAttachments([1])
        self._name = 'eudr.declaration'
        self.id = 1
        self.messages = []
    def __iter__(self):
        yield self
    def message_post(self, body=None, subtype_xmlid=None):
        self.messages.append(body)


def test_error_message_posted():
    rec = FakeDeclaration()
    rec.action_ai_analyze()
    assert any('boom' in m for m in rec.messages)
