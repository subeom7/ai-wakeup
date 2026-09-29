from __future__ import annotations
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from ai_wakeup.core import (JobSpec, WakeupError, absolute_time, build_command, duration,
                            resolve_executable, safe_text, session_uuid, serialize_spec, deserialize_spec)

SID = "0199a213-81c0-7800-8aa1-bbab2a035a53"


def spec(provider="codex", **kwargs):
    return replace(JobSpec(provider, SID, str(Path.cwd()), "continue", (str(Path(sys.executable).resolve()),)), **kwargs)


class CoreTests(unittest.TestCase):
    def test_duration_units(self):
        for value, expected in [("30s",30), ("15m",900), ("1.5h",5400), ("1d",86400)]:
            self.assertEqual(duration(value), expected)

    def test_invalid_duration(self):
        for value in ("0s", "-1s", "1", "tomorrow", "nanm", "10000d", "infh"):
            with self.subTest(value=value), self.assertRaises(WakeupError):
                duration(value)

    def test_timezone_conversion(self):
        self.assertEqual(absolute_time("2026-09-30T01:15:00+09:00"), absolute_time("2026-09-29T16:15:00Z"))

    def test_naive_time_rejected(self):
        for value in ("2026-09-30T01:15:00", "01:15", "tomorrow"):
            with self.assertRaises(WakeupError):
                absolute_time(value)

    def test_full_uuid_required(self):
        self.assertEqual(session_uuid(SID.upper()), SID)
        for value in ("--last", "0199a213", "project", "$(command)"):
            with self.assertRaises(WakeupError):
                session_uuid(value)

    def test_codex_command(self):
        args = build_command(spec())
        self.assertEqual(args[-3:], ["resume", SID, "-"])
        self.assertIn('sandbox_mode="read-only"', args)
        self.assertIn('approval_policy="never"', args)
        self.assertNotIn("continue", args)
        self.assertLess(args.index("--json"), args.index("resume"))

    def test_codex_edits_opt_in(self):
        self.assertIn('sandbox_mode="workspace-write"', build_command(spec(allow_edits=True)))

    def test_claude_command(self):
        args = build_command(spec("claude"))
        self.assertIn("--resume", args)
        self.assertIn(SID, args)
        self.assertIn("--print", args)
        self.assertIn("stream-json", args)
        self.assertEqual(args[-1], "plan")

    def test_claude_edits_opt_in(self):
        self.assertEqual(build_command(spec("claude", allow_edits=True))[-1], "acceptEdits")

    def test_no_blanket_bypass_flags(self):
        for provider in ("codex", "claude"):
            for edits in (False, True):
                args = " ".join(build_command(spec(provider, allow_edits=edits)))
                for forbidden in ("--yolo", "--full-auto", "danger-full-access", "bypassPermissions", "dangerously"):
                    self.assertNotIn(forbidden, args)

    def test_prompt_is_not_command_line(self):
        prompt = '한국어\n$(touch injected); & echo "hello" %PATH%'
        self.assertNotIn(prompt, build_command(spec(prompt=prompt)))

    def test_model_is_one_argument(self):
        args = build_command(spec(model="test-model"))
        self.assertEqual(args[args.index("--model")+1], "test-model")

    def test_invalid_prompt_and_settings(self):
        for changes in ({"prompt":""}, {"prompt":"x\0x"}, {"prompt":"한"*20000},
                        {"model":"--yolo"}, {"retry_seconds":0}, {"timeout_seconds":float("nan")}, {"cwd":"relative"}):
            with self.subTest(changes=tuple(changes)), self.assertRaises(WakeupError):
                spec(**changes).validate()

    def test_roundtrip(self):
        value = spec(prompt="한글 test", allow_edits=True)
        self.assertEqual(deserialize_spec(serialize_spec(value)), value)

    def test_terminal_controls_removed(self):
        cleaned = safe_text("\x1b[31mred\x1b[0m\x00\x9b\u202e\n한글")
        self.assertEqual(cleaned, "red\n한글")

    def test_native_executable_resolution(self):
        self.assertEqual(resolve_executable("codex", sys.executable), (str(Path(sys.executable).resolve()),))

    def test_shell_scripts_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            shim = Path(root)/"claude.cmd"
            shim.write_text("echo unsafe")
            with self.assertRaises(WakeupError):
                resolve_executable("claude", str(shim))

    def test_codex_npm_shim_uses_node_without_shell(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            shim = base/"codex.cmd"
            shim.write_text("arbitrary wrapper is not executed")
            js = base/"node_modules"/"@openai"/"codex"/"bin"/"codex.js"
            js.parent.mkdir(parents=True)
            js.write_text("// fixture")
            with patch("ai_wakeup.core.shutil.which", return_value=sys.executable):
                self.assertEqual(resolve_executable("codex", str(shim)), (str(Path(sys.executable).resolve()), str(js.resolve())))

    def test_missing_executable(self):
        with patch("ai_wakeup.core.shutil.which", return_value=None), self.assertRaises(WakeupError):
            resolve_executable("codex")
