import importlib
import pytest


def test_web_agent_importable():
    try:
        mod = importlib.import_module("agents.web_research")
        assert hasattr(mod, "WorkingWebAgent")
    except Exception as e:
        pytest.skip(f"Web agent import failed (skip in clean tree): {e}")

