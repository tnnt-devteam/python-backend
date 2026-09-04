import io
from django.test import SimpleTestCase
from scoreboard.parsers import parse_xlog_line, XlogParser
from scoreboard.tests.helpers import xlog_line


class ParseXlogLineTests(SimpleTestCase):

    def test_value_may_contain_equals_sign(self):
        entry = parse_xlog_line(
            'name=alice\tdeath=killed by a pet called a=b\n')
        self.assertEqual(entry['death'], 'killed by a pet called a=b')
        self.assertEqual(entry['name'], 'alice')

    def test_numeric_fields_are_converted(self):
        entry = parse_xlog_line(
            xlog_line(turns='1234', conduct='0x1f', flags='0x4'))
        self.assertEqual(entry['turns'], 1234)
        self.assertEqual(entry['conduct'], 0x1f)
        self.assertEqual(entry['flags'], 4)
        self.assertEqual(entry['role'], 'Cav')

    def test_empty_fields_and_line_endings_are_ignored(self):
        entry = parse_xlog_line('a=1\t\tb=2\t\r\n')
        self.assertEqual(entry, {'a': '1', 'b': '2'})

    def test_field_without_separator_raises(self):
        with self.assertRaisesRegex(ValueError, 'without "="'):
            parse_xlog_line('name=alice\tgarbage\n')

    def test_non_numeric_value_raises_naming_the_field(self):
        with self.assertRaisesRegex(ValueError, 'turns'):
            parse_xlog_line('turns=lots\n')

    def test_xlog_parser_skips_blank_lines(self):
        stream = io.StringIO(xlog_line(name='a') + '\n' + xlog_line(name='b'))
        entries = XlogParser().parse(stream)
        self.assertEqual([e['name'] for e in entries], ['a', 'b'])
