import importlib.util
import sys
import types
from pathlib import Path


if "requests" not in sys.modules:
    requests = types.ModuleType("requests")
    requests.Session = object
    sys.modules["requests"] = requests
if "dotenv" not in sys.modules:
    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda *_args, **_kwargs: None
    sys.modules["dotenv"] = dotenv

MODULE_PATH = Path(__file__).resolve().parents[1] / "host-services" / "enphase_token_refresh.py"
spec = importlib.util.spec_from_file_location("enphase_token_refresh", MODULE_PATH)
enphase_token_refresh = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["enphase_token_refresh"] = enphase_token_refresh
spec.loader.exec_module(enphase_token_refresh)


def test_write_token_file_creates_or_replaces_with_restricted_permissions(tmp_path):
    token_file = tmp_path / ".token"

    enphase_token_refresh.write_token_file("first-token", token_file)
    enphase_token_refresh.write_token_file("second-token", token_file)

    assert token_file.read_text() == "second-token\n"
    assert token_file.stat().st_mode & 0o777 == 0o600


def test_login_entrez_extracts_session_id():
    class Response:
        url = "https://entrez.enphaseenergy.com/login"
        headers = {"content-type": "text/html"}
        text = '<input type="hidden" name="session_id" value="abc123">'
        status_code = 200

        def raise_for_status(self):
            pass

    class Session:
        def get(self, url, timeout):
            assert url == "https://entrez.enphaseenergy.com/login"
            assert timeout == 15
            return Response()

        def post(self, url, data, timeout):
            assert url == "https://entrez.enphaseenergy.com/login"
            assert data == {"username": "user", "password": "pass"}
            assert timeout == 15
            return Response()

    assert enphase_token_refresh.login_entrez(Session(), "user", "pass") == "abc123"


def test_fetch_token_rejects_short_response():
    class Response:
        url = "https://entrez.enphaseenergy.com/entrez_tokens"
        headers = {"content-type": "text/plain"}
        text = "too-short"
        status_code = 200

        def raise_for_status(self):
            pass

    class Session:
        def post(self, url, data, timeout):
            assert url == "https://entrez.enphaseenergy.com/entrez_tokens"
            assert data == {"session_id": "sid", "serial_num": "serial"}
            assert timeout == 15
            return Response()

    try:
        enphase_token_refresh.fetch_token(Session(), "sid", "serial")
    except RuntimeError as exc:
        assert "Unexpected token response" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError")


def test_extract_session_id_handles_json_response():
    assert enphase_token_refresh._extract_session_id('{"session_id": "json-session"}') == (
        "json-session"
    )


def test_debug_recorder_writes_sanitized_response_body(tmp_path):
    class Response:
        url = "https://example.invalid"
        headers = {"content-type": "text/html"}
        text = 'password=secret session_id="abc123" access_token=tokenvalue'
        status_code = 200

    debug = enphase_token_refresh.DebugRecorder(tmp_path)
    debug.response("changed-flow", Response())

    artifact = tmp_path / "01-changed-flow.txt"
    body = artifact.read_text()
    assert "secret" not in body
    assert "tokenvalue" not in body
    assert "abc123" not in body
    assert artifact.stat().st_mode & 0o777 == 0o600
