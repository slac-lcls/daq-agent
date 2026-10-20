import json
import unittest

from daq_agent.chat_answers import validate_answer
from daq_agent.model_json import load_model_json
from daq_agent.reports import validate_findings


class ModelJSONTests(unittest.TestCase):
    def test_literal_whitespace_preserves_text_and_existing_escapes(self):
        expected = {'observation': 'SYNTHETIC "quote" and \\path\nnext\tcolumn\rreturn',
                    'other': 'already escaped\nwith \\n characters', 'nested': [{'text': 'line1\nline2'}]}
        text = json.dumps(expected)
        # Change only the first field and nested string to model-style raw whitespace.
        text = text.replace('path\\n', 'path\n').replace('next\\t', 'next\t').replace('column\\r', 'column\r')
        text = text.replace('line1\\n', 'line1\n')
        for supplied in (text, '```json\n' + text + '\n```'):
            self.assertEqual(load_model_json(supplied), expected)
        self.assertEqual(load_model_json(json.dumps(expected)), expected)

    def test_malformed_structure_and_other_controls_remain_rejected(self):
        for text in ('{"x":"a\nb",}', '{"x":"a\nb"', '{"x":"a\nb"} trailing',
                     '{"x":"a\nb", "y": "bad\\q"}', '{"x":"bad\\\nline"}',
                     '{"x":"a\nb", "y":"nul\x00"}', '{"x":"escape\x1b[31m"}'):
            with self.subTest(text=repr(text)), self.assertRaises(json.JSONDecodeError):
                load_model_json(text)

    def test_schema_and_citation_validation_still_follow_normalization(self):
        sources = [{'id': 'log-1', 'lines': 2}]
        findings = {'summary': 'Synthetic', 'limitations': ['Synthetic only'], 'findings': [{
            'title': 'Synthetic', 'observation': 'line1\nline2', 'hypothesis': 'Unknown',
            'next_check': 'Review', 'evidence': [{'source': 'log-1', 'line_start': 1, 'line_end': 2}]}]}
        def raw(value):
            return json.dumps(value).replace('line1\\nline2', 'line1\nline2')
        self.assertEqual(validate_findings(raw(findings), sources), findings)
        findings['findings'][0]['evidence'][0]['line_end'] = 3
        with self.assertRaisesRegex(ValueError, 'outside'):
            validate_findings(raw(findings), sources)
        answer = {'answer': 'line1\nline2', 'limitations': ['Synthetic only'],
                  'citations': [{'source': 'log-1', 'line_start': 1, 'line_end': 2}]}
        self.assertEqual(validate_answer(raw(answer), sources), answer)
        answer['citations'][0]['source'] = 'log-2'
        with self.assertRaisesRegex(ValueError, 'not supplied'):
            validate_answer(raw(answer), sources)
        with self.assertRaisesRegex(ValueError, 'requires'):
            validate_answer('{"answer":"line1\nline2"}', sources)


if __name__ == '__main__':
    unittest.main()
