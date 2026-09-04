"""
Shared helpers for the scoreboard test suite.

Xlog lines are generated rather than taken from the tracked test-*.xlog
files: those hold 2024 games, which pollxlogs filters out as being before
TOURNAMENT_START.
"""
from datetime import timedelta
from tnnt import settings

# A complete TNNT xlogfile record, in the field order the game writes.
# starttime/endtime are filled in by xlog_line().
BASE_FIELDS = [
    ('server', 'us.hardfought.org'), ('version', '3.6.7'), ('points', '147'),
    ('deathdnum', '2'), ('deathlev', '3'), ('maxlvl', '3'), ('hp', '0'),
    ('maxhp', '15'), ('deaths', '1'), ('deathdate', '20261107'),
    ('birthdate', '20261107'), ('uid', '5'), ('role', 'Cav'),
    ('race', 'Gno'), ('gender', 'Mal'), ('align', 'Neu'), ('name', 'alice'),
    ('death', 'killed by a jackal'), ('conduct', '0x1fdfcf'),
    ('turns', '441'), ('achieve', '0x0'), ('realtime', '275'),
    ('starttime', None), ('endtime', None), ('gender0', 'Mal'),
    ('align0', 'Neu'), ('flags', '0x0'), ('tnntachieve0', '0x0'),
    ('tnntachieve1', '0x0'), ('tnntachieve2', '0x0'), ('tnntachieve3', '0x0'),
    ('tnntachieve4', '0x0'), ('tnntachieve5', '0x0'), ('while', 'sleeping'),
]

# achieve bits used by pollxlogs
ACHIEVE_ASCENDED = 0x100
ACHIEVE_AMULET = 0x20
ACHIEVE_MINES_SOKO = 0x600


def in_window(days=4, seconds=0):
    """Unix timestamp `days` (+ `seconds`) after the tournament start."""
    when = settings.TOURNAMENT_START + timedelta(days=days, seconds=seconds)
    return int(when.timestamp())


def xlog_line(**overrides):
    """
    Return one newline-terminated xlog record. Keyword arguments override
    fields; a value of None removes the field. `start` sets starttime (a
    Unix timestamp, default a few days into the tournament) and endtime is
    derived from it and realtime.
    """
    fields = dict(BASE_FIELDS)
    start = overrides.pop('start', None) or in_window()
    for key, value in overrides.items():
        if value is None:
            del fields[key]
        else:
            fields[key] = str(value)
    if 'starttime' in fields:
        fields['starttime'] = str(start)
    if 'endtime' in fields:
        fields['endtime'] = str(start + int(fields.get('realtime', '0')))
    return '\t'.join('%s=%s' % kv for kv in fields.items()) + '\n'
