"""MCP 管理 + 预设导入导出/存为预设。"""

import json
import tomllib

import pytest

from ctxbox.core import mcp, providers
from ctxbox.core.mcp import McpServer, delete_server, list_servers, upsert_server
from ctxbox.core.providers import (
    PresetStore,
    export_presets,
    import_presets,
    preset_from_current,
)


@pytest.fixture
def fake_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp, "claude_config_path", lambda: tmp_path / "claude.json")
    monkeypatch.setattr(mcp, "codex_config_path", lambda: tmp_path / "codex.toml")
    monkeypatch.setattr(providers, "claude_settings_path", lambda: tmp_path / "settings.json")
    monkeypatch.setattr(providers, "_backup_root", lambda: tmp_path / "backups")
    return tmp_path


def make_server(name="test-mcp", tool="claude-code") -> McpServer:
    return McpServer(
        name=name,
        command="python",
        args=["D:/tools/server.py", "--fast"],
        env={"API_KEY": "x", "DEBUG": "1"},
        startup_timeout_sec=60.0,
        tool=tool,
    )


class TestClaudeMcp:
    def test_upsert_list_delete_and_preserve(self, fake_paths):
        cfg = fake_paths / "claude.json"
        cfg.write_text(json.dumps({"userID": "u1", "mcpServers": {}}), encoding="utf-8")
        upsert_server("claude-code", make_server())
        servers = list_servers("claude-code")
        assert len(servers) == 1
        s = servers[0]
        assert s.command == "python" and s.args == ["D:/tools/server.py", "--fast"]
        assert s.env == {"API_KEY": "x", "DEBUG": "1"}
        # 其他顶层键保留
        data = json.loads(cfg.read_text(encoding="utf-8"))
        assert data["userID"] == "u1"
        assert data["mcpServers"]["test-mcp"]["type"] == "stdio"
        # 覆盖同名不重复
        upsert_server("claude-code", make_server())
        assert len(list_servers("claude-code")) == 1
        # 删除
        delete_server("claude-code", "test-mcp")
        assert list_servers("claude-code") == []
        assert list((fake_paths / "backups").iterdir())

    def test_missing_file_safe(self, fake_paths):
        assert list_servers("claude-code") == []
        delete_server("claude-code", "ghost")  # 不存在的文件+名字不报错


class TestCodexMcp:
    def test_upsert_preserves_rest(self, fake_paths):
        cfg = fake_paths / "codex.toml"
        cfg.write_text(
            'model = "gpt-6.1"\n\n[mcp_servers.old]\ntype = "stdio"\ncommand = "node"\n',
            encoding="utf-8",
        )
        upsert_server("codex", make_server(tool="codex"))
        data = tomllib.loads(cfg.read_text(encoding="utf-8"))
        assert data["model"] == "gpt-6.1"
        assert data["mcp_servers"]["old"]["command"] == "node"
        new = data["mcp_servers"]["test-mcp"]
        assert new["command"] == "python"
        assert new["startup_timeout_sec"] == 60.0
        assert new["env"]["DEBUG"] == "1"
        servers = {s.name: s for s in list_servers("codex")}
        assert servers["test-mcp"].startup_timeout_sec == 60.0
        delete_server("codex", "test-mcp")
        assert "test-mcp" not in tomllib.loads(cfg.read_text(encoding="utf-8"))["mcp_servers"]


class TestPresetImportExport:
    def test_roundtrip_and_id_collision(self, fake_paths, tmp_path):
        store = PresetStore(tmp_path / "providers.json")
        from ctxbox.core.providers import ProviderPreset

        store.upsert(ProviderPreset(tool="codex", name="A", base_url="https://a", id="p1"))
        out = tmp_path / "share.json"
        assert export_presets(out, store) == 1
        # 导入回同一个库: id 冲突 -> 换新 id, 不覆盖
        n = import_presets(out, store)
        assert n == 1
        assert len(store.list()) == 2
        assert {p.name for p in store.list()} == {"A"}
        assert len({p.id for p in store.list()}) == 2

    def test_import_bad_file(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text('{"no_presets": true}', encoding="utf-8")
        with pytest.raises(ValueError):
            import_presets(f, PresetStore(tmp_path / "p.json"))

    def test_preset_from_current(self, fake_paths):
        (fake_paths / "settings.json").write_text(
            json.dumps(
                {
                    "env": {
                        "ANTHROPIC_BASE_URL": "https://cur.example.com",
                        "ANTHROPIC_AUTH_TOKEN": "sk-cur-123456",
                        "ANTHROPIC_MODEL": "claude-x",
                    }
                }
            ),
            encoding="utf-8",
        )
        p = preset_from_current("claude-code")
        assert p.base_url == "https://cur.example.com"
        assert p.api_key == "sk-cur-123456"
        assert p.model == "claude-x"
        assert p.name == ""  # 名称由用户在编辑器里填
