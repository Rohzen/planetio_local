import base64
import io
import zipfile
import sys
import types
import importlib.util
from pathlib import Path


repo_root = Path(__file__).resolve().parents[1]
sys.path.append(str(repo_root))

class _FieldsStub(types.SimpleNamespace):
    def __getattr__(self, name):  # pragma: no cover - defensive fallback
        return lambda *args, **kwargs: None


odoo = types.ModuleType("odoo")
odoo.api = types.SimpleNamespace()
odoo.fields = _FieldsStub()
odoo.models = types.SimpleNamespace(Model=object, AbstractModel=object)
sys.modules.setdefault("odoo", odoo)


pkg_path = repo_root / "ai_gateway"
services_path = pkg_path / "services"

ai_gateway_pkg = types.ModuleType("ai_gateway")
ai_gateway_pkg.__path__ = [str(pkg_path)]
sys.modules.setdefault("ai_gateway", ai_gateway_pkg)

services_pkg = types.ModuleType("ai_gateway.services")
services_pkg.__path__ = [str(services_path)]
sys.modules.setdefault("ai_gateway.services", services_pkg)


spec = importlib.util.spec_from_file_location(
    "ai_gateway.services.ai_service",
    services_path / "ai_service.py",
    submodule_search_locations=[str(services_path)],
)
ai_service = importlib.util.module_from_spec(spec)
sys.modules["ai_gateway.services.ai_service"] = ai_service
spec.loader.exec_module(ai_service)


class DummyAttachment:
    def __init__(self, raw_bytes, mimetype, name):
        self.datas = base64.b64encode(raw_bytes).decode()
        self.mimetype = mimetype
        self.name = name
        self.display_name = name


def _make_docx(text):
    xml = (
        "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
        "<w:body><w:p><w:r><w:t>" + text + "</w:t></w:r></w:p></w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("word/document.xml", xml)
    return buffer.getvalue()


def test_plain_text_attachment_to_text():
    att = DummyAttachment(b"Situazione deforestazione", "text/plain", "report.txt")
    extracted = ai_service._attachment_to_text(None, att)
    assert "Situazione deforestazione" in extracted


def test_docx_attachment_to_text():
    docx_bytes = _make_docx("Allerta deforestazione in crescita")
    att = DummyAttachment(
        docx_bytes,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "sintesi.docx",
    )
    extracted = ai_service._attachment_to_text(None, att)
    assert "Allerta deforestazione" in extracted
