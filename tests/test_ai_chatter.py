import json
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


class DummyAttachment:
    def __init__(self, attachment_id, visible):
        self.id = attachment_id
        self.eudr_document_visible = visible


class DummyAttachments:
    def __init__(self, attachments):
        self._attachments = list(attachments)

    def __iter__(self):
        return iter(self._attachments)

    def __bool__(self):
        return bool(self._attachments)

    @property
    def ids(self):
        return [attachment.id for attachment in self._attachments]

    def filtered(self, func):
        return DummyAttachments(filter(func, self._attachments))


class FakeAiRequest:
    def __init__(self, status='error', response_text='', error_message='boom'):
        self.status = status
        self.error_message = error_message
        self.response_text = response_text

    def run_now(self):
        pass


class FakeAiRequestModel:
    def __init__(self):
        self.status = 'error'
        self.response_text = ''
        self.error_message = 'boom'
        self.last_create_vals = None

    def create(self, vals):
        self.last_create_vals = vals
        return FakeAiRequest(
            status=self.status,
            response_text=self.response_text,
            error_message=self.error_message,
        )


class FakeEnv(dict):
    pass


class FakeAttachmentModel:
    def __init__(self):
        self.created = []

    def create(self, vals):
        self.created.append(vals)
        return vals


class FakeConfigParameter:
    def sudo(self):
        return self

    def get_param(self, key, default=None):
        return default


class FakeDeclaration(mod.PlanetioSummarizeWizard):
    def __init__(self, request_model=None, attachments=None):
        attachment_model = FakeAttachmentModel()
        request_model = request_model or FakeAiRequestModel()
        attachments = attachments or [DummyAttachment(1, True)]
        self.env = FakeEnv({
            'ai.request': request_model,
            'ir.attachment': attachment_model,
            'ir.config_parameter': FakeConfigParameter(),
            'eudr.declaration.line': types.SimpleNamespace(),
        })
        self.attachment_ids = DummyAttachments(attachments)
        self._name = 'eudr.declaration'
        self.id = 1
        self.display_name = 'Fake Declaration'
        self.messages = []
        self._fields = {'ai_alert_ids': object(), 'ai_action_ids': object()}
        self.ai_alert_ids = []
        self.ai_action_ids = []
        self.line_ids = [
            types.SimpleNamespace(
                id=1,
                display_name='Field One',
                name='Field One',
                external_uid='F1',
                farmer_id_code='FIELD-1',
                defor_details_json=None,
                defor_provider=None,
                defor_alerts=None,
                defor_area_ha=None,
                external_message=None,
            ),
            types.SimpleNamespace(
                id=2,
                display_name='Field Two',
                name='Field Two',
                external_uid='F2',
                farmer_id_code='FIELD-2',
                defor_details_json=None,
                defor_provider=None,
                defor_alerts=None,
                defor_area_ha=None,
                external_message=None,
            ),
        ]
        self.attachment_model = attachment_model
        self.request_model = request_model

    def __iter__(self):
        yield self

    def message_post(self, body=None, subtype_xmlid=None):
        self.messages.append(body)

    def write(self, vals):
        if 'ai_alert_ids' in vals:
            self.ai_alert_ids = self._apply_commands(self.ai_alert_ids, vals['ai_alert_ids'])
        if 'ai_action_ids' in vals:
            self.ai_action_ids = self._apply_commands(self.ai_action_ids, vals['ai_action_ids'])
        return True

    @staticmethod
    def _apply_commands(current, commands):
        result = list(current)
        for command in commands:
            if not isinstance(command, (list, tuple)):
                continue
            if command[0] == 5:
                result = []
            elif command[0] == 0 and len(command) >= 3:
                result.append(dict(command[2]))
        return result

    def _summary_to_pdf(self, text, record):
        return (text or '').encode('utf-8'), 'text/plain'


def test_error_message_posted():
    rec = FakeDeclaration()
    rec.action_ai_analyze()
    assert any('boom' in m for m in rec.messages)


def test_structured_response_creates_records():
    request_model = FakeAiRequestModel()
    request_model.status = 'done'
    request_model.error_message = ''
    request_model.response_text = json.dumps({
        'alerts': [
            {'field_id': 'F1', 'description': 'Possible illegal clearing detected.'},
            {'field_id': 'FIELD-2', 'field_label': 'Second Plot', 'description': 'Moderate risk observed.'},
        ],
        'actions': [
            {'field_id': 2, 'description': 'Schedule on-site verification within 30 days.'},
        ],
    })

    rec = FakeDeclaration(request_model=request_model)
    rec.action_ai_analyze()

    assert len(rec.ai_alert_ids) == 2
    assert rec.ai_alert_ids[0]['field_identifier'] == 'F1'
    assert rec.ai_alert_ids[0]['line_id'] == 1
    assert len(rec.ai_action_ids) == 1
    assert rec.ai_action_ids[0]['field_identifier'] == '2'
    assert rec.ai_action_ids[0]['line_id'] == 2
    assert rec.ai_action_ids[0]['line_label'] == 'Field Two'
    assert rec.ai_action_ids[0]['description']
    assert rec.attachment_model.created, 'Expected a summary attachment to be created'


def test_only_visible_attachments_are_sent_to_ai():
    request_model = FakeAiRequestModel()
    request_model.status = 'done'
    request_model.error_message = ''
    request_model.response_text = json.dumps({'alerts': [], 'actions': []})

    attachments = [
        DummyAttachment(101, True),
        DummyAttachment(202, False),
    ]

    rec = FakeDeclaration(request_model=request_model, attachments=attachments)
    rec.action_ai_analyze()

    attachment_command = rec.request_model.last_create_vals['attachment_ids']
    assert attachment_command == [(6, 0, [101])]


def test_actions_with_recommendation_key_are_preserved():
    request_model = FakeAiRequestModel()
    request_model.status = 'done'
    request_model.error_message = ''
    request_model.response_text = json.dumps(
        {
            'alerts': [
                {
                    'field_label': 'Field One',
                    'description': 'Canopy loss observed in satellite imagery.',
                }
            ],
            'actions': [
                {
                    'field_id': 'FIELD-2',
                    'recommendation': 'Engage the farmer to review compliance plan.',
                }
            ],
        }
    )

    rec = FakeDeclaration(request_model=request_model)
    rec.action_ai_analyze()

    assert rec.ai_action_ids, 'Expected at least one action to be stored'
    assert rec.ai_action_ids[0]['description'] == 'Engage the farmer to review compliance plan.'


def test_actions_dictionary_payload_is_parsed():
    request_model = FakeAiRequestModel()
    request_model.status = 'done'
    request_model.error_message = ''
    request_model.response_text = json.dumps(
        {
            'alerts': [],
            'actions': {
                'FIELD-1': 'Schedule a compliance review.',
                'FIELD-2': {
                    'field_label': 'Second Plot',
                    'details': 'Engage local team for remediation.',
                },
            },
        }
    )

    rec = FakeDeclaration(request_model=request_model)
    rec.action_ai_analyze()

    assert len(rec.ai_action_ids) == 2
    descriptions = {item['description'] for item in rec.ai_action_ids}
    assert 'Schedule a compliance review.' in descriptions
    assert 'Engage local team for remediation.' in descriptions


def test_actions_string_payload_is_preserved():
    request_model = FakeAiRequestModel()
    request_model.status = 'done'
    request_model.error_message = ''
    request_model.response_text = json.dumps(
        {
            'alerts': [
                {
                    'field_label': 'Field One',
                    'description': 'Canopy loss observed in satellite imagery.',
                }
            ],
            'actions': 'Maintain regular monitoring of compliance documentation.',
        }
    )

    rec = FakeDeclaration(request_model=request_model)
    rec.action_ai_analyze()

    assert rec.ai_action_ids, 'Expected the string payload to create an action record'
    assert (
        rec.ai_action_ids[0]['description']
        == 'Maintain regular monitoring of compliance documentation.'
    )


def test_corrective_actions_key_is_used_when_actions_missing():
    request_model = FakeAiRequestModel()
    request_model.status = 'done'
    request_model.error_message = ''
    request_model.response_text = json.dumps(
        {
            'alerts': [],
            'corrective_actions': [
                {
                    'field_label': 'Plot C',
                    'description': 'Implement buffer zones along the river banks.',
                }
            ],
        }
    )

    rec = FakeDeclaration(request_model=request_model)
    rec.action_ai_analyze()

    assert rec.ai_action_ids, 'Expected corrective_actions data to be parsed as actions'
    assert (
        rec.ai_action_ids[0]['description']
        == 'Implement buffer zones along the river banks.'
    )
