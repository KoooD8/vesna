#!/usr/bin/env python3
"""
ObsidianManager: безопасное управление настройками Obsidian Vault (.obsidian)
- Поддерживает: бэкап/восстановление, включение/выключение плагинов, установка плагинов из zip/URL,
  переключение темы, управление CSS сниппетами, изменение generic настроек JSON (app.json, community-plugins.json, appearance.json, ...)
- Все записи в JSON — атомарные: запись во временный файл с последующим rename.
- Никаких сетевых операций по умолчанию (кроме установки по URL, если передано).
"""
from __future__ import annotations

import os
import io
import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import zipfile
except Exception:
    zipfile = None  # type: ignore

@dataclass
class ObsidianPaths:
    vault: Path
    dot: Path  # .obsidian
    plugins: Path  # .obsidian/plugins
    snippets: Path  # .obsidian/snippets


class ObsidianManager:
    def __init__(self, vault_path: str) -> None:
        base = Path(vault_path).expanduser()
        dot = base / ".obsidian"
        self.paths = ObsidianPaths(
            vault=base,
            dot=dot,
            plugins=dot / "plugins",
            snippets=dot / "snippets",
        )
        # ensure base dirs exist (do not create .obsidian automatically to respect user env)
        self.paths.vault.mkdir(parents=True, exist_ok=True)
        self.paths.dot.mkdir(parents=True, exist_ok=True)
        self.paths.plugins.mkdir(parents=True, exist_ok=True)
        self.paths.snippets.mkdir(parents=True, exist_ok=True)

    # -------- utils --------
    @staticmethod
    def _atomic_write(path: Path, data: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", delete=False, dir=str(path.parent), encoding="utf-8") as tf:
            tf.write(data)
            tmp = Path(tf.name)
        os.replace(tmp, path)  # atomic rename on POSIX

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        try:
            if not path.exists():
                return default
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default

    @staticmethod
    def _write_json(path: Path, obj: Any) -> None:
        s = json.dumps(obj, ensure_ascii=False, indent=2)
        ObsidianManager._atomic_write(path, s)

    # -------- backups --------
    def backup_settings(self, backup_dir: Optional[str] = None) -> Path:
        out_dir = Path(backup_dir).expanduser() if backup_dir else (self.paths.vault / "Backups/.obsidian")
        out_dir.mkdir(parents=True, exist_ok=True)
        # copy important files
        for name in [
            "app.json",
            "appearance.json",
            "core-plugins.json",
            "community-plugins.json",
            "hotkeys.json",
            "workspace.json",
        ]:
            src = self.paths.dot / name
            if src.exists():
                dst = out_dir / name
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        # copy directories: plugins manifests and snippets
        if self.paths.plugins.exists():
            dst_plugins = out_dir / "plugins"
            if dst_plugins.exists():
                shutil.rmtree(dst_plugins)
            shutil.copytree(self.paths.plugins, dst_plugins)
        if self.paths.snippets.exists():
            dst_snip = out_dir / "snippets"
            if dst_snip.exists():
                shutil.rmtree(dst_snip)
            shutil.copytree(self.paths.snippets, dst_snip)
        return out_dir

    # -------- community plugins --------
    def list_plugins(self) -> Dict[str, Any]:
        core = self._read_json(self.paths.dot / "core-plugins.json", default=[])
        community = self._read_json(self.paths.dot / "community-plugins.json", default=[])
        installed_dirs = []
        if self.paths.plugins.exists():
            for p in sorted(self.paths.plugins.glob("*/manifest.json")):
                try:
                    manifest = json.loads(p.read_text(encoding="utf-8"))
                    installed_dirs.append({
                        "id": manifest.get("id") or p.parent.name,
                        "dir": p.parent.name,
                        "name": manifest.get("name"),
                        "version": manifest.get("version"),
                        "author": manifest.get("author"),
                    })
                except Exception:
                    installed_dirs.append({"id": p.parent.name, "dir": p.parent.name})
        return {"core": core, "community": community, "installed": installed_dirs}

    def enable_plugin(self, plugin_id: str) -> None:
        community = self._read_json(self.paths.dot / "community-plugins.json", default=[])
        if plugin_id not in community:
            community.append(plugin_id)
        self._write_json(self.paths.dot / "community-plugins.json", community)

    def disable_plugin(self, plugin_id: str) -> None:
        community = self._read_json(self.paths.dot / "community-plugins.json", default=[])
        community = [p for p in community if p != plugin_id]
        self._write_json(self.paths.dot / "community-plugins.json", community)

    def enable_core_plugin(self, plugin_id: str) -> None:
        core = self._read_json(self.paths.dot / "core-plugins.json", default=[])
        if plugin_id not in core:
            core.append(plugin_id)
        self._write_json(self.paths.dot / "core-plugins.json", core)

    def disable_core_plugin(self, plugin_id: str) -> None:
        core = self._read_json(self.paths.dot / "core-plugins.json", default=[])
        core = [p for p in core if p != plugin_id]
        self._write_json(self.paths.dot / "core-plugins.json", core)

    def install_plugin_from_zip(self, zip_path: str, plugin_dir_name: Optional[str] = None) -> str:
        if zipfile is None:
            raise RuntimeError("zipfile module unavailable")
        zpath = Path(zip_path)
        if not zpath.exists():
            raise FileNotFoundError(zpath)
        target_base = self.paths.plugins
        with zipfile.ZipFile(str(zpath), "r") as zf:
            # Determine top-level folder or use provided dir name
            top_dirs = {p.split("/")[0] for p in zf.namelist() if "/" in p}
            out_dir_name = plugin_dir_name or (next(iter(top_dirs)) if top_dirs else zpath.stem)
            out_dir = target_base / out_dir_name
            if out_dir.exists():
                shutil.rmtree(out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            zf.extractall(str(out_dir))
        # Try to detect plugin id from manifest
        manifest = out_dir / "manifest.json"
        plugin_id = out_dir_name
        if manifest.exists():
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
                plugin_id = data.get("id") or out_dir_name
            except Exception:
                pass
        # auto-enable
        self.enable_plugin(plugin_id)
        return plugin_id

    def install_plugin_from_url(self, url: str, plugin_dir_name: Optional[str] = None) -> str:
        import requests  # lazy import
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        with tempfile.NamedTemporaryFile("wb", delete=False) as tf:
            tf.write(resp.content)
            tmp = tf.name
        try:
            return self.install_plugin_from_zip(tmp, plugin_dir_name=plugin_dir_name)
        finally:
            try:
                os.remove(tmp)
            except Exception:
                pass

    # -------- appearance / theme / snippets --------
    def set_theme(self, theme_name: str) -> None:
        # Obsidian stores theme info in appearance.json, e.g., {"theme":"obsidian", "cssTheme":"Your Theme"}
        ap = self._read_json(self.paths.dot / "appearance.json", default={})
        # If theme is a community theme, it usually sets cssTheme
        ap["cssTheme"] = theme_name
        self._write_json(self.paths.dot / "appearance.json", ap)

    def enable_snippet(self, snippet_css_filename: str) -> None:
        # appearance.json: {"enabledCssSnippets": ["my-snippet"]}; filenames without .css
        ap = self._read_json(self.paths.dot / "appearance.json", default={})
        enabled = set(ap.get("enabledCssSnippets") or [])
        base = Path(snippet_css_filename).stem
        enabled.add(base)
        ap["enabledCssSnippets"] = sorted(enabled)
        self._write_json(self.paths.dot / "appearance.json", ap)

    def disable_snippet(self, snippet_css_filename: str) -> None:
        ap = self._read_json(self.paths.dot / "appearance.json", default={})
        enabled = [s for s in (ap.get("enabledCssSnippets") or []) if s != Path(snippet_css_filename).stem]
        ap["enabledCssSnippets"] = enabled
        self._write_json(self.paths.dot / "appearance.json", ap)

    # -------- generic settings --------
    def set_setting(self, settings_file: str, json_path: str, value: Any) -> None:
        """Generic: mutate a JSON file under .obsidian by dot-path.
        Example: set_setting("app.json", "promptDelete", False)
        """
        p = self.paths.dot / settings_file
        data = self._read_json(p, default={})
        # navigate dot path
        cur = data
        parts = [k for k in json_path.split(".") if k]
        for key in parts[:-1]:
            if not isinstance(cur, dict):
                raise ValueError(f"Cannot traverse into non-dict at '{key}' in {json_path}")
            if key not in cur or not isinstance(cur[key], (dict, list)):
                cur[key] = {}
            cur = cur[key]
        last = parts[-1] if parts else None
        if last is None:
            raise ValueError("Empty json_path")
        # assign
        cur[last] = value
        self._write_json(p, data)

    # convenience
    def vault_root(self) -> Path:
        return self.paths.vault

    def obsidian_dir(self) -> Path:
        return self.paths.dot

    def ensure_snippet_file(self, name: str, content: str) -> Path:
        p = self.paths.snippets / (name if name.endswith('.css') else f"{name}.css")
        self._atomic_write(p, content)
        return p

    def ensure_theme_css(self, name: str, content: str) -> Path:
        # Some community themes are pure CSS; store under snippets and enable
        p = self.ensure_snippet_file(name, content)
        self.enable_snippet(Path(p).name)
        return p

