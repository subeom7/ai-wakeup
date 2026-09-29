import tempfile
import unittest
from pathlib import Path

from ai_wakeup.events import EventClassifier, classify_file, error_info

SID = "0199a213-81c0-7800-8aa1-bbab2a035a53"


class EventTests(unittest.TestCase):
    def test_codex_success(self):
        c=EventClassifier("codex",SID)
        c.feed({"type":"turn.completed"})
        self.assertEqual(c.outcome(0).kind,"success")

    def test_codex_structured_rate(self):
        c=EventClassifier("codex",SID)
        c.feed({"type":"turn.failed","error":{"code":"usage_limit_exceeded","retry_after_seconds":30}})
        o=c.outcome(1)
        self.assertEqual((o.kind,o.retry_after),("rate_limit",30))

    def test_human_banner_only_inside_failure(self):
        c=EventClassifier("codex",SID)
        c.feed({"type":"turn.failed","error":{"message":"You've hit your usage limit. Try again later."}})
        self.assertEqual(c.outcome(1).kind,"rate_limit")

    def test_tool_output_never_triggers_retry(self):
        c=EventClassifier("codex",SID)
        c.feed({"type":"item.completed","item":{"type":"command_execution","output":"You've hit your usage limit"}})
        self.assertNotEqual(c.outcome(1).kind,"rate_limit")

    def test_assistant_text_never_triggers_retry(self):
        c=EventClassifier("claude",SID)
        c.feed({"type":"assistant","message":{"content":[{"type":"text","text":"You've hit your usage limit"}]}})
        self.assertNotEqual(c.outcome(1).kind,"rate_limit")

    def test_auth_error_not_retried(self):
        self.assertFalse(error_info({"type":"authentication_error","message":"You've hit your usage limit"})[0])

    def test_insufficient_quota_not_retried(self):
        self.assertFalse(error_info({"code":"insufficient_quota"})[0])

    def test_transient_error_then_success(self):
        c=EventClassifier("codex",SID)
        c.feed({"type":"error","message":"Rate limit exceeded"})
        c.feed({"type":"turn.completed"})
        self.assertEqual(c.outcome(0).kind,"success")

    def test_success_with_nonzero_exit_not_success(self):
        c=EventClassifier("codex",SID)
        c.feed({"type":"turn.completed"})
        self.assertEqual(c.outcome(2).kind,"failure")

    def test_unknown_zero_exit_requires_review(self):
        self.assertEqual(EventClassifier("codex",SID).outcome(0).kind,"review")

    def test_wrong_session_requires_review(self):
        for provider,event in [("codex",{"type":"thread.started","thread_id":"different"}),
                               ("claude",{"type":"system","subtype":"init","session_id":"different"})]:
            c=EventClassifier(provider,SID)
            c.feed(event)
            self.assertEqual(c.outcome(0).kind,"review")

    def test_claude_result(self):
        c=EventClassifier("claude",SID)
        c.feed({"type":"result","subtype":"success","is_error":False,"session_id":SID})
        self.assertEqual(c.outcome(0).kind,"success")

    def test_claude_permission_denials(self):
        c=EventClassifier("claude",SID)
        c.feed({"type":"result","subtype":"success","is_error":False,"permission_denials":[{"tool_name":"Bash"}]})
        self.assertEqual(c.outcome(0).kind,"review")

    def test_claude_rate_error(self):
        c=EventClassifier("claude",SID)
        c.feed({"type":"result","subtype":"error_during_execution","is_error":True,"errors":["Rate limit exceeded"]})
        self.assertEqual(c.outcome(1).kind,"rate_limit")

    def test_retry_hint_must_be_numeric_finite(self):
        for hint in (True, "tomorrow", -4, float("nan")):
            self.assertIsNone(error_info({"code":"rate_limit_error","retry_after":hint})[2])

    def test_bad_lines_ignored(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/"log"
            p.write_bytes(b'not json\n{"type":"turn.completed"}\n')
            self.assertEqual(classify_file("codex",SID,p,0).kind,"success")

    def test_huge_event_requires_review(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/"log"
            p.write_bytes(b"x"*(1024*1024+5))
            self.assertEqual(classify_file("codex",SID,p,0).kind,"review")

    def test_top_level_error_envelope_is_not_an_api_error_code(self):
        c=EventClassifier("codex",SID)
        c.feed({"type":"error","message":"You've hit your usage limit. Try again later."})
        self.assertEqual(c.outcome(1).kind,"rate_limit")
