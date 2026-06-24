from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT / "minyad-agent"
sys.path.insert(0, str(AGENT_DIR))

# Provide lightweight stubs so importing agent.py does not require optional runtime packages.
sys.modules.setdefault("anthropic", SimpleNamespace(Anthropic=lambda **_kwargs: None))
sys.modules.setdefault("apscheduler", SimpleNamespace())
sys.modules.setdefault("apscheduler.schedulers", SimpleNamespace())
sys.modules.setdefault("apscheduler.schedulers.blocking", SimpleNamespace(BlockingScheduler=lambda: None))

spec = importlib.util.spec_from_file_location("minyad_agent_main", AGENT_DIR / "agent.py")
agent = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(agent)


def test_claude_skip_reason_when_agent_disabled() -> None:
    assert agent.claude_skip_reason({"enabled": False, "token_guard_enabled": True, "min_tokens_remaining": 5000}, 1500) == "waiting_for_claude"


def test_claude_skip_reason_when_token_guard_active() -> None:
    settings = {"enabled": True, "token_guard_enabled": True, "min_tokens_remaining": 5000, "tokens_remaining": 4999}

    assert agent.claude_skip_reason(settings, 1500) == "token_guard_active"


def test_claude_skip_reason_allows_call_when_enabled_and_guard_clear() -> None:
    settings = {"enabled": True, "token_guard_enabled": True, "min_tokens_remaining": 5000, "tokens_remaining": 6000}

    assert agent.claude_skip_reason(settings, 1500) is None
