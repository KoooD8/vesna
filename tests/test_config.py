import os
from pathlib import Path


def test_default_vault_env(monkeypatch):
    # Arrange
    monkeypatch.setenv(
        "AI_STACK_DEFAULT_VAULT",
        "/tmp/test_obsidian_vault",
    )
    from config import load_config

    # Act
    cfg = load_config(path="/non/existent/config.yaml")

    # Assert
    assert cfg.vault_path == "/tmp/test_obsidian_vault"


def test_env_config_path_can_be_missing(tmp_path, monkeypatch):
    # Arrange: no file present, should fall back to defaults
    p = tmp_path / "missing.yaml"
    monkeypatch.setenv("AI_STACK_CONFIG", str(p))

    from config import load_config

    # Act
    cfg = load_config()

    # Assert
    assert isinstance(cfg.vault_path, str)
    assert cfg.vault_path
    assert cfg.folders.sources

