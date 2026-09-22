from dataclasses import replace
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from daq_agent.config import Settings, load_settings
from daq_agent.log_analysis import analyze_logs
from daq_agent.runtime import audit_evidence_access, session_config
from daq_agent.skill_sources import cache_directory, parse_source, read_snapshot, sync_skills


class SkillSourceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.real_run = subprocess.run
        self.git("init", "--quiet")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        for name in ("psana-daq", "psana-daq-logs"):
            directory = self.repo / "skills" / name
            directory.mkdir(parents=True)
            (directory / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Test diagnostic guidance\n---\nVersion one\n")
        reference = self.repo / "skills/psana-daq-logs/reference"
        reference.mkdir()
        (reference / "patterns.md").write_text("Support file\n")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "one")
        self.revision = self.git("rev-parse", "HEAD").strip()
        self.source = parse_source({"repository": "https://example.invalid/org/repo", "branch": "development",
                                    "revision": self.revision, "directory": "skills"})
        self.cache = self.root / "cache"

    def git(self, *args):
        return self.real_run(["git", "-C", str(self.repo), *args], capture_output=True, text=True, check=True).stdout

    def fetch_local_fixture(self, args, **kwargs):
        # All Git operations are real; only the network transport is substituted.
        if "fetch" in args:
            self.assertEqual(args[-2:], [self.source.repository, self.source.revision])
            args = [*args[:1], "-c", "protocol.file.allow=always", *args[1:-2], str(self.repo), args[-1]]
        return self.real_run(args, **kwargs)

    def sync(self):
        with patch("daq_agent.skill_sources.subprocess.run", side_effect=self.fetch_local_fixture):
            return sync_skills(self.source, self.cache)

    def test_pinned_commit_complete_directories_and_offline_reuse(self):
        skill = self.repo / "skills/psana-daq/SKILL.md"
        skill.write_text(skill.read_text().replace("Version one", "Version two"))
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "advance branch")
        directory = self.sync()
        metadata, content = read_snapshot(directory, self.source)
        self.assertIn(b"Version one", content["psana-daq/SKILL.md"])
        self.assertEqual(content["psana-daq-logs/reference/patterns.md"], b"Support file\n")
        self.assertEqual(metadata["source"]["revision"], self.revision)
        with patch("daq_agent.skill_sources.subprocess.run", side_effect=AssertionError("network")):
            self.assertEqual(sync_skills(self.source, self.cache), directory)
        (directory / "psana-daq/SKILL.md").write_text("tampered")
        with self.assertRaisesRegex(ValueError, "integrity"):
            read_snapshot(directory, self.source)

    def test_unsafe_source_configuration_rejected(self):
        valid = {"repository": self.source.repository, "branch": "dev", "revision": self.revision, "directory": "skills"}
        for field, value in (("revision", "main"), ("directory", "../skills"), ("directory", "/skills"),
                             ("repository", "file:///tmp/repo"), ("repository", "https://user:secret@host/org/repo"),
                             ("skills", ["log-triage"]), ("skills", ["../bad"])):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                parse_source({**valid, field: value})

    def test_upstream_symlink_rejected(self):
        (self.repo / "skills/psana-daq/unsafe").symlink_to("/etc/passwd")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "symlink")
        self.source = replace(self.source, revision=self.git("rev-parse", "HEAD").strip())
        with self.assertRaisesRegex(ValueError, "regular files"):
            self.sync()
        self.assertFalse(cache_directory(self.source, self.cache).exists())

    def test_missing_or_invalid_frontmatter_rejected(self):
        skill = self.repo / "skills/psana-daq/SKILL.md"
        skill.write_text("---\nname: wrong\ndescription: test\n---\n")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "invalid metadata")
        self.source = replace(self.source, revision=self.git("rev-parse", "HEAD").strip())
        with self.assertRaisesRegex(ValueError, "frontmatter"):
            self.sync()

    def test_analysis_retains_skills_without_fetching_or_model_calls(self):
        self.sync()
        settings = Settings("tmo", "America/Los_Angeles", "slac/example", daq_skills=self.source)
        log = self.root / "input.log"
        log.write_text("SYNTHETIC error\n")
        with patch("daq_agent.skill_sources.subprocess.run", side_effect=AssertionError("network")):
            output = analyze_logs(settings, "2026-09-20", "2026-09-21", [log], self.root / "output", None,
                                  "missing", prepare_only=True, skills_cache=self.cache)
        manifest = json.loads((output / "manifest.json").read_text())
        self.assertEqual(manifest["required_upstream_skills"], list(self.source.skills))
        self.assertEqual(manifest["upstream_skills"]["source"]["revision"], self.revision)
        self.assertTrue((output / "upstream-skills/psana-daq-logs/reference/patterns.md").is_file())
        self.assertIn("live-discovery steps do not apply", (output / "prompt.txt").read_text())
        with self.assertRaisesRegex(ValueError, "sync-skills"):
            analyze_logs(settings, "2026-09-20", "2026-09-21", [log], self.root / "missing", None,
                         "missing", prepare_only=True, skills_cache=self.root / "absent")
        fallback = analyze_logs(settings, "2026-09-20", "2026-09-21", [log], self.root / "fallback", None,
                                "missing", prepare_only=True, local_skills_only=True)
        self.assertEqual(json.loads((fallback / "manifest.json").read_text())["upstream_skills"]["status"],
                         "disabled_by_request")

    def test_permissions_and_audit_require_selected_skills(self):
        workspace = self.root / "workspace"
        reference = workspace / ".opencode/skills/psana-daq-logs/reference/patterns.md"
        reference.parent.mkdir(parents=True)
        reference.write_text("test")
        names = list(self.source.skills)
        config = session_config(workspace, {}, "slac/example", names)
        self.assertEqual(config["permission"]["*"], "deny")
        self.assertEqual(config["permission"]["skill"], {"*": "deny", "log-triage": "allow",
                                                        "psana-daq": "allow", "psana-daq-logs": "allow"})
        events = self.root / "events.jsonl"
        def tool(name, args):
            return json.dumps({"type": "tool_use", "part": {"tool": name,
                               "state": {"status": "completed", "input": args}}}) + "\n"
        lines = [tool("skill", {"name": name}) for name in ["log-triage", *names]]
        lines += [tool("read", {"filePath": str(workspace / "evidence/log-1.txt")}),
                  tool("read", {"filePath": str(reference)})]
        sources = [{"id": "log-1", "snapshot": "evidence/log-1.txt"}]
        events.write_text("".join(lines))
        audit = audit_evidence_access(events, workspace, sources, names)
        self.assertEqual(audit["skills_loaded"], sorted(["log-triage", *names]))
        relative_lines = [line.replace(str(workspace) + "/", "") for line in lines]
        events.write_text("".join(relative_lines))
        self.assertEqual(audit_evidence_access(events, workspace, sources, names)["sources_read"], ["log-1"])
        events.write_text("".join(lines) + tool("read", {"filePath": "../outside.txt"}))
        with self.assertRaisesRegex(ValueError, "unexpected"):
            audit_evidence_access(events, workspace, sources, names)
        events.write_text("".join(lines[1:]))
        with self.assertRaisesRegex(ValueError, "required skills"):
            audit_evidence_access(events, workspace, sources, names)
        events.write_text("".join(lines) + tool("skill", {"name": "psana-daq-monitor"}))
        with self.assertRaisesRegex(ValueError, "unexpected"):
            audit_evidence_access(events, workspace, sources, names)

    def test_tmo_config_has_exact_pin(self):
        settings = load_settings(Path("config/hutches/tmo.toml"))
        self.assertEqual(settings.daq_skills.revision, "606038fed893ce788f1b865418ae6a569f66dc1d")
        self.assertEqual(settings.daq_skills.skills, ('psana-daq', 'psana-daq-logs', 'psana-daq-control', 'psana-daq-monitor', 'psana-configdb', 'psana-daq-snapshot'))
        from importlib.resources import files
        from daq_agent.skill_sources import descriptor
        import tomllib
        packaged = tomllib.loads(files("daq_agent").joinpath("profiles/tmo.toml").read_text())
        self.assertEqual(descriptor(settings.daq_skills), packaged["daq_skills"])

    def test_composed_suite_retains_overview_references_and_chat(self):
        from chat_fixtures import write_report, fake_chat_runtime
        from daq_agent.chat import create_conversation, answer_question, load_conversation
        from daq_agent.report_store import load_report
        from daq_agent.skill_sources import retain_skills
        names = ("psana-daq", "psana-daq-logs", "psana-daq-control",
                 "psana-daq-monitor", "psana-configdb", "psana-daq-snapshot")
        for name in names[2:]:
            directory = self.repo / "skills" / name
            directory.mkdir()
            # Exercise the real suite's >128 KiB size, without vendoring its content.
            (directory / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: Synthetic guidance\n---\n" + "guidance\n" * 4000)
        (self.repo / "skills/README.md").write_text("Synthetic suite overview\n")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "composed suite")
        self.source = replace(self.source, skills=names, revision=self.git("rev-parse", "HEAD").strip())
        metadata, contents = read_snapshot(self.sync(), self.source)
        self.assertGreater(sum(map(len, contents.values())), 128 * 1024)
        self.assertIn("README.md", contents)
        self.assertIn("psana-daq-logs/reference/patterns.md", contents)
        report_path = write_report(self.root / "reports")
        retained = retain_skills(self.source, report_path, self.cache)
        manifest_path = report_path / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest.update(upstream_skills=retained, required_upstream_skills=list(names))
        manifest_path.write_text(json.dumps(manifest))
        conversation = create_conversation(load_report(report_path), "example/test", self.root / "chats")
        self.assertEqual(load_conversation(conversation)[2], contents)
        provider = self.root / "provider.json"
        provider.write_text(json.dumps({"provider": {"example": {"npm": "@ai-sdk/anthropic", "models": {"test": {}},
            "options": {"apiKey": "{env:SYNTHETIC_KEY}", "baseURL": "https://example.invalid/v1"}}}}))
        settings = Settings("tmo", "UTC", "example/test", provider_config=str(provider),
                            opencode=str(fake_chat_runtime(self.root)))
        answer_question(conversation, settings, "Explain finding 1")
        turn = json.loads((conversation / "turns/0001/manifest.json").read_text())
        self.assertEqual(turn["runtime_audit"]["skills_loaded"], sorted(["report-chat", *names]))
        (report_path / "upstream-skills/README.md").write_text("tampered")
        with self.assertRaisesRegex(ValueError, "integrity"):
            load_conversation(conversation)

    def test_suite_overview_read_permission_and_audit(self):
        workspace = self.root / "workspace"
        overview = workspace / ".opencode/skills/README.md"
        overview.parent.mkdir(parents=True)
        overview.write_text("Synthetic overview")
        names = list(self.source.skills)
        for task, primary in (("report", "log-triage"), ("chat", "report-chat")):
            with self.subTest(task=task):
                config = session_config(workspace, {}, "example/test", names, task=task)
                self.assertEqual(config["permission"]["read"][str(overview)], "allow")
                self.assertEqual(config["permission"]["*"], "deny")
                self.assertEqual(config["mcp"], {})
                self.assertNotIn(str(overview), session_config(workspace, {}, "example/test", task=task)["permission"]["read"])
                events = self.root / "events.jsonl"
                def tool(name, args):
                    return json.dumps({"type": "tool_use", "part": {"tool": name,
                        "state": {"status": "completed", "input": args}}}) + "\n"
                lines = [tool("skill", {"name": name}) for name in [primary, *names]]
                lines.append(tool("read", {"filePath": str(overview)}))
                events.write_text("".join(lines))
                audit_evidence_access(events, workspace, [], names, task=task)
                for forbidden in (".opencode/skills/other.md", ".opencode/skills/../outside.md"):
                    events.write_text("".join(lines) + tool("read", {"filePath": forbidden}))
                    with self.assertRaisesRegex(ValueError, "unexpected"):
                        audit_evidence_access(events, workspace, [], names, task=task)

    def test_snapshot_path_rejects_unselected_files(self):
        from daq_agent.skill_sources import valid_snapshot_path
        for name in ("../README.md", "README.md/child", "other.md", "psana-daq/../README.md",
                     "psana-daq-history/SKILL.md", "/README.md", "./README.md"):
            with self.subTest(name=name):
                self.assertFalse(valid_snapshot_path(name, self.source.skills))
