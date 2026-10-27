import logging
import unittest

from ambient_logging import AmbientFormatter, REASONS


class AmbientLoggingTests(unittest.TestCase):
    def render(self, text, *args):
        record = logging.LogRecord('george.ambient', logging.INFO, '', 0, text, args, None)
        result = AmbientFormatter('%(message)s').format(record)
        self.assertEqual(record.msg, text)
        self.assertEqual(record.args, args)
        return result

    def test_reason_is_japanese_and_ids_are_preserved(self):
        text = self.render('generation_skipped reason=%s channel=%s message=%s',
                           'model_unclear', 897078546030280708, 1564408103519391896)
        self.assertIn('AIが話題や文脈をつかめないと判断した', text)
        self.assertIn('チャンネルID：897078546030280708', text)
        self.assertIn('メッセージID：1564408103519391896', text)
        self.assertNotIn('reason=', text)
        self.assertNotIn('generation_skipped', text)

    def test_all_known_reasons_and_event_types_are_readable(self):
        for code, label in REASONS.items():
            self.assertIn('理由：' + label, self.render('skip reason=%s channel=1', code))
        for code in ('reaction_added', 'attempt_started', 'reply_sent'):
            self.assertNotIn(code, self.render(code + ' channel=1 message=2'))
