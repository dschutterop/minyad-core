from __future__ import annotations

import ast
from pathlib import Path

HOST_SERVICES = Path(__file__).resolve().parents[1] / "host-services"
BRIDGES = {
    "dsmr_bridge.py": {
        "on_source_connect": 6,
        "on_source_disconnect": 6,
        "on_target_connect": 6,
        "on_target_disconnect": 6,
    },
    "enphase_bridge.py": {
        "on_connect": 6,
        "on_disconnect": 6,
    },
    "goodwe_bridge.py": {
        "on_connect": 6,
        "on_disconnect": 6,
    },
}


def test_host_bridges_use_callback_api_v2_and_v2_signatures() -> None:
    for filename, expected_callbacks in BRIDGES.items():
        source = (HOST_SERVICES / filename).read_text()
        tree = ast.parse(source)

        client_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "Client"
        ]
        assert client_calls, filename
        for call in client_calls:
            assert call.args, f"{filename} MQTT client must select a callback API explicitly"
            assert ast.unparse(call.args[0]) == "mqtt.CallbackAPIVersion.VERSION2"

        functions = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for callback, expected_arg_count in expected_callbacks.items():
            assert callback in functions, f"{filename} is missing {callback}"
            assert len(functions[callback].args.args) == expected_arg_count
