import unittest
from unittest.mock import patch
from progress_profiles import profile_for, george_name, apply_george_names, george_naming_context
from gacha import vierge_character_card
from gacha_commands import gacha_comment, favorite_details


class GeorgeNameTests(unittest.TestCase):
    def test_alias_lookup_custom_name_and_empty_fallback(self):
        record = profile_for('日向美海')
        with patch.dict(record, progressGeorgeName='美海ちゃん'):
            self.assertEqual(george_name('美海'), '美海ちゃん')
            self.assertIn('美海ちゃん', george_naming_context('日向美海'))
        with patch.dict(record, progressGeorgeName='  '):
            self.assertEqual(george_name('美海'), '日向美海')
        self.assertEqual(george_name('不明な名前'), '不明な名前')

    def test_generated_names_do_not_duplicate_honorifics_or_change_identity_labels(self):
        with patch.dict(profile_for('ロザリー'), progressGeorgeName='ロザリーちゃん'):
            self.assertEqual(apply_george_names('ロザリーとロザリーちゃんだぜ'), 'ロザリーちゃんとロザリーちゃんだぜ')
            self.assertEqual(apply_george_names('ロザリーの右腕と`/プログレス ロザリー`'), 'ロザリーの右腕と`/プログレス ロザリー`')
            self.assertEqual(apply_george_names('ロザリー【幻影のドレス】'), 'ロザリー【幻影のドレス】')
        with patch.dict(profile_for('日向美海'), progressGeorgeName='美海'):
            self.assertEqual(apply_george_names('日向美海ちゃんと日向美海'), '美海と美海')

    def test_fallback_comment_uses_setting_but_card_identity_does_not(self):
        card = vierge_character_card('ロザリー', 'UR')
        with patch.dict(profile_for('ロザリー'), progressGeorgeName='ロザリー先生'):
            self.assertIn('ロザリー先生', gacha_comment('vierge', [card], favorite=('vierge', card, 1)))
            self.assertIn('ロザリー先生', favorite_details(card))
        self.assertEqual(card.character, 'ロザリー')
        self.assertEqual(card.name, 'ロザリー')
