"""配置中心: 预设 CRUD / 一键启用 / 配置保留 / token 脱敏。"""

import json

import pytest
import tomllib

from ctxbox.core import providers
from ctxbox.core.providers import (
    PresetStore,
    ProviderPreset,
    active_preset_id,
    apply_preset,
    dump_toml,
    read_current,
)


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """所有真实配置路径重定向到临时 HOME, 绝不碰真机文件。"""
    monkeypatch.setattr(providers, "claude_settings_path", lambda: tmp_path / "claude.json")
    monkeypatch.setattr(providers, "codex_config_path", lambda: tmp_path / "codex.toml")
    monkeypatch.setattr(providers, "_backup_root", lambda: tmp_path / "backups")
    return tmp_path


def make_preset(tool="claude-code", **kw) -> ProviderPreset:
    defaults = dict(
        tool=tool,
        name="中转A",
        base_url="https://api.example.com/v1",
        api_key="sk-test-1234567890abcdef",
        model="claude-opus-4-8" if tool == "claude-code" else "gpt-6.1",
        id="p1",
    )
    defaults.update(kw)
    return ProviderPreset(**defaults)


class TestPresetStore:
    def test_crud(self, tmp_path):
        store = PresetStore(tmp_path / "providers.json")
        p = make_preset()
        store.upsert(p)
        assert store.get("p1").name == "中转A"
        store.upsert(make_preset(name="改名了"))
        assert len(store.list()) == 1
        assert store.get("p1").name == "改名了"
        assert store.delete("p1") is True
        assert store.list() == []
        assert store.delete("p1") is False

    def test_filter_by_tool(self, tmp_path):
        store = PresetStore(tmp_path / "providers.json")
        store.upsert(make_preset(tool="claude-code"))
        store.upsert(make_preset(tool="codex", id="p2"))
        assert [p.id for p in store.list("codex")] == ["p2"]

    def test_corrupt_file_returns_empty(self, tmp_path):
        f = tmp_path / "providers.json"
        f.write_text("{broken", encoding="utf-8")
        assert PresetStore(f).list() == []

    def test_masked_key(self):
        p = make_preset()
        assert p.masked_key() == "sk-t…cdef"
        assert "1234567890" not in p.masked_key()


class TestClaudeApply:
    def test_apply_writes_env_and_preserves_rest(self, fake_home):
        path = fake_home / "claude.json"
        path.write_text(
            json.dumps({"env": {"OTHER": "keep"}, "permissions": {"allow": ["Bash"]}}),
            encoding="utf-8",
        )
        apply_preset(make_preset())
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["env"]["ANTHROPIC_BASE_URL"] == "https://api.example.com/v1"
        assert data["env"]["ANTHROPIC_AUTH_TOKEN"] == "sk-test-1234567890abcdef"
        assert data["env"]["ANTHROPIC_MODEL"] == "claude-opus-4-8"
        assert data["env"]["OTHER"] == "keep"  # 其余 env 保留
        assert data["permissions"] == {"allow": ["Bash"]}  # 其余顶层键保留
        assert list((fake_home / "backups").iterdir())  # 有备份

    def test_apply_creates_file_when_missing(self, fake_home):
        path = apply_preset(make_preset())
        env = json.loads(path.read_text(encoding="utf-8"))["env"]
        assert env["ANTHROPIC_BASE_URL"]

    def test_read_current_and_active_match(self, fake_home):
        apply_preset(make_preset())
        cur = read_current("claude-code")
        assert cur["base_url"] == "https://api.example.com/v1"
        assert cur["model"] == "claude-opus-4-8"
        store = PresetStore(fake_home / "providers.json")
        store.upsert(make_preset())
        assert active_preset_id("claude-code", store) == "p1"


CODEX_EXISTING = """model_provider = "custom"
model = "old-model"
disable_response_storage = true

[model_providers.custom]
name = "Old"
base_url = "https://old.example.com/v1"
wire_api = "responses"
requires_openai_auth = false
experimental_bearer_token = "sk-old"

[mcp_servers.adb]
type = "stdio"
command = "python"
args = ["D:\\\\tools\\\\server.py"]
startup_timeout_sec = 120.0

[mcp_servers.adb.env]
PATH = 'D:\\tools'
"""


class TestCodexApply:
    def test_apply_adds_provider_and_preserves_mcp(self, fake_home):
        path = fake_home / "codex.toml"
        path.write_text(CODEX_EXISTING, encoding="utf-8")
        apply_preset(make_preset(tool="codex"))
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        assert data["model_provider"] == "ctxbox_p1"
        new = data["model_providers"]["ctxbox_p1"]
        assert new["base_url"] == "https://api.example.com/v1"
        assert new["experimental_bearer_token"] == "sk-test-1234567890abcdef"
        assert data["model"] == "gpt-6.1"
        # 旧 provider 和 MCP 段原样保留
        assert data["model_providers"]["custom"]["base_url"] == "https://old.example.com/v1"
        assert data["mcp_servers"]["adb"]["command"] == "python"
        assert data["mcp_servers"]["adb"]["startup_timeout_sec"] == 120.0
        assert data["mcp_servers"]["adb"]["args"] == ["D:\\tools\\server.py"]
        assert data["disable_response_storage"] is True

    def test_apply_is_idempotent_per_preset(self, fake_home):
        path = fake_home / "codex.toml"
        path.write_text(CODEX_EXISTING, encoding="utf-8")
        apply_preset(make_preset(tool="codex"))
        apply_preset(make_preset(tool="codex"))
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        providers = [k for k in data["model_providers"] if k == "ctxbox_p1"]
        assert len(providers) == 1  # 不重复堆积

    def test_read_current(self, fake_home):
        path = fake_home / "codex.toml"
        path.write_text(CODEX_EXISTING, encoding="utf-8")
        cur = read_current("codex")
        assert cur["provider_id"] == "custom"
        assert cur["base_url"] == "https://old.example.com/v1"
        assert cur["model"] == "old-model"


class TestTomlDump:
    def test_scalars_and_nesting(self):
        text = dump_toml(
            {
                "a": 1,
                "b": True,
                "c": 'x"y',
                "list": ["a", "b"],
                "t": {"nested": 1.5, "deep": {"k": "v"}},
            }
        )
        data = tomllib.loads(text)
        assert data["a"] == 1 and data["b"] is True
        assert data["c"] == 'x"y'
        assert data["list"] == ["a", "b"]
        assert data["t"]["nested"] == 1.5
        assert data["t"]["deep"]["k"] == "v"

    def test_roundtrip_real_codex_config(self):
        data = tomllib.loads(CODEX_EXISTING)
        again = tomllib.loads(dump_toml(data))
        assert again == data


def test_toml_special_char_keys_quoted():
    """真实 codex 配置含 [plugins.documents@openai-primary-runtime] 这类
    带 @ 的段名, 不加引号会生成非法 TOML (真机回归)。"""
    data = tomllib.loads(
        '[plugins]\n\n[plugins."documents@openai-primary-runtime"]\nenabled = true\n'
    )
    text = dump_toml(data)
    again = tomllib.loads(text)
    assert again == data
