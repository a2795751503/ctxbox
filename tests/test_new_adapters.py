"""New adapters: kimi-code (real-format wire.jsonl), opencode (SQLite),
gemini-cli, aider."""

import json
import sqlite3
from pathlib import Path

from ctxbox.core.adapters.base import all_adapters, get_adapter
from ctxbox.core.model.schema import Role

FIXTURES = Path(__file__).parent / "fixtures"


def test_registry_has_new_adapters():
    names = {a.name for a in all_adapters()}
    assert {"kimi-code", "opencode", "gemini-cli", "aider"} <= names


class TestKimiCode:
    def setup_method(self):
        self.adapter = get_adapter("kimi-code")
        self.session = self.adapter.parse(
            FIXTURES / "kimi_code" / "session_test" / "agents" / "main" / "wire.jsonl"
        )

    def test_session_id_and_project(self):
        assert self.session.id == "session_test"

    def test_roles_and_parts(self):
        roles = [t.role for t in self.session.turns]
        assert roles == [Role.USER, Role.ASSISTANT, Role.ASSISTANT, Role.TOOL, Role.ASSISTANT]
        kinds = [p.kind for t in self.session.turns for p in t.parts]
        assert "thinking" in kinds and "tool_call" in kinds and "tool_result" in kinds

    def test_model_extracted(self):
        assert self.session.meta.get("model") == "kimi-code/k3"

    def test_title_from_real_user_question(self):
        assert "401" in self.session.title

    def test_roundtrip(self, tmp_path):
        p = tmp_path / "wd_demo_12345678" / "session_rt" / "agents" / "main" / "wire.jsonl"
        p.parent.mkdir(parents=True)
        p.write_bytes(self.adapter.serialize(self.session))
        again = self.adapter.parse(p)
        assert again.id == "session_rt"
        assert sum(1 for t in again.turns if t.role == Role.USER) == 1


class TestOpenCode:
    def _make_db(self, tmp_path: Path) -> Path:
        db = tmp_path / "opencode.db"
        conn = sqlite3.connect(db)
        conn.executescript(
            """CREATE TABLE session (id TEXT PRIMARY KEY, project_id TEXT,
                parent_id TEXT, directory TEXT, title TEXT, version TEXT,
                agent TEXT, model TEXT, time_created INTEGER, time_updated INTEGER);
               CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT,
                time_created INTEGER, data TEXT);
               CREATE TABLE part (id TEXT PRIMARY KEY, message_id TEXT,
                session_id TEXT, time_created INTEGER, data TEXT);"""
        )
        conn.execute(
            "INSERT INTO session VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "ses_1",
                "p1",
                None,
                "D:\\proj",
                "Demo chat",
                "1.2.0",
                "build",
                json.dumps({"id": "gpt-5.5"}),
                1786000000000,
                1786000060000,
            ),
        )
        conn.execute(
            "INSERT INTO message VALUES (?,?,?,?)",
            ("m1", "ses_1", 1786000001000, json.dumps({"role": "user"})),
        )
        conn.execute(
            "INSERT INTO message VALUES (?,?,?,?)",
            (
                "m2",
                "ses_1",
                1786000002000,
                json.dumps(
                    {
                        "role": "assistant",
                        "modelID": "gpt-5.5",
                        "tokens": {"input": 100, "output": 50},
                    }
                ),
            ),
        )
        conn.execute(
            "INSERT INTO part VALUES (?,?,?,?,?)",
            (
                "pt1",
                "m1",
                "ses_1",
                1786000001500,
                json.dumps({"type": "text", "text": "add a retry to login"}),
            ),
        )
        conn.execute(
            "INSERT INTO part VALUES (?,?,?,?,?)",
            (
                "pt2",
                "m2",
                "ses_1",
                1786000002500,
                json.dumps({"type": "reasoning", "text": "find the auth call"}),
            ),
        )
        conn.execute(
            "INSERT INTO part VALUES (?,?,?,?,?)",
            (
                "pt3",
                "m2",
                "ses_1",
                1786000003000,
                json.dumps({"type": "text", "text": "Added a retry with backoff."}),
            ),
        )
        conn.execute(
            "INSERT INTO part VALUES (?,?,?,?,?)",
            (
                "pt4",
                "m2",
                "ses_1",
                1786000003500,
                json.dumps(
                    {
                        "type": "tool",
                        "tool": "edit",
                        "state": {"status": "completed", "output": "ok"},
                    }
                ),
            ),
        )
        conn.commit()
        conn.close()
        return db

    def test_iter_sessions(self, tmp_path):
        adapter = get_adapter("opencode")
        db = self._make_db(tmp_path)
        sessions = list(adapter.iter_sessions(db))
        assert len(sessions) == 1
        s = sessions[0]
        assert s.id == "ses_1" and s.title == "Demo chat"
        assert s.project_dir == "D:\\proj"
        roles = [t.role for t in s.turns]
        assert Role.USER in roles and Role.ASSISTANT in roles and Role.TOOL in roles
        kinds = [p.kind for t in s.turns for p in t.parts]
        assert "thinking" in kinds and "text" in kinds and "tool_result" in kinds

    def test_readonly_open_on_live_db(self, tmp_path):
        # a second writer connection may hold the db; we must still open ro fine
        adapter = get_adapter("opencode")
        db = self._make_db(tmp_path)
        s = adapter.parse(db)
        assert s.id == "ses_1"


class TestGeminiCli:
    def test_parse(self):
        adapter = get_adapter("gemini-cli")
        s = adapter.parse(FIXTURES / "gemini" / "chats" / "session-demo.json")
        assert [t.role for t in s.turns] == [Role.USER, Role.ASSISTANT, Role.ASSISTANT]
        kinds = [p.kind for t in s.turns for p in t.parts]
        assert "tool_call" in kinds


class TestAider:
    def test_parse(self):
        adapter = get_adapter("aider")
        s = adapter.parse(FIXTURES / "aider" / ".aider.chat.history.md")
        roles = [t.role for t in s.turns]
        assert roles[0] == Role.USER
        assert "split parser.py" in s.turns[0].text()
        assert Role.ASSISTANT in roles

    def test_roundtrip_markers(self):
        adapter = get_adapter("aider")
        s = adapter.parse(FIXTURES / "aider" / ".aider.chat.history.md")
        md = adapter.serialize(s).decode("utf-8")
        assert md.count("> ") >= 2
