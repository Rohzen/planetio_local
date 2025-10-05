import importlib
import importlib
import sys
import types
from pathlib import Path


repo_root = Path(__file__).resolve().parents[1]
sys.path.append(str(repo_root))

planetio_pkg = sys.modules.setdefault("planetio", types.ModuleType("planetio"))
planetio_pkg.__path__ = [str((repo_root / "planetio").resolve())]

services_pkg = types.ModuleType("planetio.services")
services_pkg.__path__ = [str((repo_root / "planetio" / "services").resolve())]
planetio_pkg.services = services_pkg
sys.modules["planetio.services"] = services_pkg

module = importlib.import_module("planetio.services.eudr_client_retrieve")
EUDRRetrievalClient = module.EUDRRetrievalClient


def test_sanitize_root_tag_defaults():
    assert EUDRRetrievalClient._sanitize_root_tag(None) == "retrieveDdsNumberRequest"
    assert EUDRRetrievalClient._sanitize_root_tag("") == "retrieveDdsNumberRequest"


def test_sanitize_root_tag_removes_namespace_and_spaces():
    assert (
        EUDRRetrievalClient._sanitize_root_tag(" retr:RetrieveDdsNumberRequest  ")
        == "RetrieveDdsNumberRequest"
    )


def test_custom_root_tag_is_used_when_building_xml():
    client = EUDRRetrievalClient(
        "https://example.com",
        "user",
        "apikey",
        retrieval_root_tag="RetrieveDdsNumberRequest",
    )
    xml = client.build_retrieval_xml("1234")
    assert "<retr:RetrieveDdsNumberRequest" in xml


def test_invalid_custom_root_tag_falls_back_to_default():
    client = EUDRRetrievalClient(
        "https://example.com",
        "user",
        "apikey",
        retrieval_root_tag="123 invalid",
    )
    xml = client.build_retrieval_xml("abcd")
    assert "<retr:retrieveDdsNumberRequest" in xml
