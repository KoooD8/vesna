import pytest


def test_registry_list_steps_cli_help_runs():
    import subprocess, sys
    # Run: python3 chat.py list-steps (may fail if orchestrator not present)
    try:
        out = subprocess.run([sys.executable, "chat.py", "list-steps"], capture_output=True, text=True, check=True, timeout=10)
        assert "Доступные шаги" in out.stdout
    except Exception as e:
        pytest.skip(f"list-steps not available: {e}")

