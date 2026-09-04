from rest_framework.parsers import BaseParser

dec_fields = ['points', 'turns', 'realtime', 'maxlvl', 'starttime', 'endtime']
hex_fields = [
    'flags', 'achieve', 'conduct', 'tnntachieve0', 'tnntachieve1',
    'tnntachieve2', 'tnntachieve3', 'tnntachieve4', 'tnntachieve5'
]

FIELD_DELIMITER = '\t'
KEY_VALUE_SEPARATOR = '='


def convert_if_numeric(key, value):
    if key in dec_fields:
        return int(value, 10)
    elif key in hex_fields:
        return int(value, 16)
    else:
        return value


def parse_xlog_line(line):
    """
    Parse one xlogfile line ("key=value<TAB>key=value...") into a dict.

    Numeric fields are converted with convert_if_numeric(). Empty fields
    (e.g. from a trailing tab) are skipped. A value may itself contain '='
    (NetHack does not escape it in death strings or object/monster names),
    so each field is split on its first '=' only.

    Raises ValueError for a field with no '=' or for a numeric field whose
    value does not parse; the caller decides whether to skip the line.
    """
    entry = {}
    for field in line.rstrip('\r\n').split(FIELD_DELIMITER):
        if not field:
            continue
        key, sep, value = field.partition(KEY_VALUE_SEPARATOR)
        if not sep:
            raise ValueError('xlog field without "=": %r' % field[:80])
        try:
            entry[key] = convert_if_numeric(key, value)
        except ValueError:
            raise ValueError('xlog field %s has a non-numeric value: %r'
                             % (key, value[:80])) from None
    return entry


class XlogParser(BaseParser):
    delimiter = FIELD_DELIMITER
    separator = KEY_VALUE_SEPARATOR

    def parse(self, stream, media_type=None, parser_context=None):
        """
        Parse xlogfile data into python primitive types.
        Input: filehandle stream e.g. from open('foo.xlog')
        Output: list of dicts, one per non-blank line, as produced by
        parse_xlog_line(). A malformed line raises ValueError. pollxlogs
        parses line by line itself so that it can skip such lines.
        """
        return [
            parse_xlog_line(line)
            for line in stream.readlines()
            if line.strip()
        ]
