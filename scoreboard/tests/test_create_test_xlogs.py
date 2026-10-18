"""
Tests for the record conversion in create_test_xlogs.py, which rewrites
games of an older tournament in the record format of the current game.
"""
import subprocess
import unittest
from unittest import mock

from django.test import SimpleTestCase, TestCase

import create_test_xlogs
from create_test_xlogs import (
    GAME_DUNGEONS, OLD_FORMATS, RecordConverter, bit_positions,
)
from scoreboard.management.commands.pollxlogs import ADDED, game_from_xlog
from scoreboard.models import Game, Source
from scoreboard.parsers import parse_xlog_line
from scoreboard.tests.helpers import in_window

# A made-up old game and the current one. The old achievement A_OLDNAME
# has the successor A_NEWNAME, A_GONE has none, and the current game added
# A_NEW and the conduct iden. Its conducts moved from bit 12 up into
# tnntconduct, except pets, and zen stayed in achieve.
OLD_POSITIONS = (
    {'A_ONE': ('tnntachieve0', 0), 'A_GONE': ('tnntachieve0', 1),
     'A_OLDNAME': ('tnntachieve1', 5), 'A_TWO': ('tnntachieve1', 6)},
    {'food': ('conduct', 0), 'elbe': ('conduct', 12),
     'pets': ('conduct', 21), 'zen': ('achieve', 12)},
)
NEW_POSITIONS = (
    {'A_TWO': ('tnntachieve0', 0), 'A_ONE': ('tnntachieve0', 3),
     'A_NEWNAME': ('tnntachieve0', 7), 'A_NEW': ('tnntachieve0', 9)},
    {'food': ('conduct', 0), 'pets': ('conduct', 13),
     'elbe': ('tnntconduct', 0), 'iden': ('tnntconduct', 14),
     'zen': ('achieve', 12)},
)
OLD_FORMAT = {
    'fixtures': None,
    'dungeons': ('The Dungeons of Doom', 'robotfindskitten'),
    'achieve_bits': 14,
}
OLD_RECORD = [
    'server=us.hardfought.org', 'version=3.6.7', 'deathdnum=1',
    'name=alice', 'death=quit', 'conduct=0x201001', 'turns=5',
    'achieve=0x5100', 'realtime=1', 'flags=0x4', 'tnntachieve0=0x3',
    'tnntachieve1=0x60',
]


@mock.patch.dict(create_test_xlogs.ACHIEVEMENT_SUCCESSORS,
                 {'A_OLDNAME': 'A_NEWNAME'}, clear=True)
class RecordConverterTests(SimpleTestCase):

    def converter(self, new_positions=NEW_POSITIONS):
        return RecordConverter(OLD_FORMAT, OLD_POSITIONS, new_positions)

    def test_converts_record(self):
        converter = self.converter()
        self.assertEqual(converter.convert(OLD_RECORD), [
            'server=us.hardfought.org', 'version=5.0.0',
            'deathdnum=%d' % GAME_DUNGEONS.index('robotfindskitten'),
            'name=alice', 'death=quit',
            # food stays at 0, pets moves to 13, elbe to tnntconduct 0;
            # iden was not tracked and is recorded as broken
            'conduct=0x2001', 'turns=5',
            # bit 14 is cleared, ascended and zen are kept
            'achieve=0x1100', 'tnntconduct=0x1',
            'realtime=1', 'flags=0x4',
            # A_TWO 0, A_ONE 3, A_OLDNAME's successor 7; A_GONE dropped
            'tnntachieve0=0x89',
        ])
        self.assertEqual(converter.dropped_seen, {'A_GONE': 1})

    def test_bit_the_old_fixtures_dont_define_exits(self):
        record = OLD_RECORD[:-1] + ['tnntachieve1=0xe0']
        with self.assertRaises(SystemExit):
            self.converter().convert(record)

    def test_record_with_tnntconduct_exits(self):
        with self.assertRaises(SystemExit):
            self.converter().convert(OLD_RECORD + ['tnntconduct=0x0'])

    def test_conduct_missing_from_current_game_exits(self):
        conducts = dict(NEW_POSITIONS[1])
        del conducts['pets']
        with self.assertRaises(SystemExit):
            self.converter((NEW_POSITIONS[0], conducts))

    def test_writes_as_many_tnntachieve_fields_as_the_game(self):
        # NUM_TNNT_ACHIEVEMENTS / 64 + 1: a full first field adds a second
        achievements = {'A_%d' % i: ('tnntachieve0', i) for i in range(63)}
        achievements.update(A_ONE=('tnntachieve0', 63))
        converted = self.converter((achievements, NEW_POSITIONS[1])).convert(
            OLD_RECORD)
        self.assertEqual(converted[-2:],
                         ['tnntachieve0=0x8000000000000000',
                          'tnntachieve1=0x0'])


def has_commit(revision):
    """True if this repository's git history has the commit."""
    try:
        result = subprocess.run(
            ['git', '-C', str(create_test_xlogs.BASE_DIR), 'cat-file',
             '-e', revision + '^{commit}'], capture_output=True)
    except OSError:
        return False
    return result.returncode == 0


@unittest.skipUnless(has_commit(OLD_FORMATS[2025]['fixtures']),
                     'needs the git history of the 2025 fixtures')
class Convert2025Tests(TestCase):
    fixtures = ['conducts', 'achievements', 'sources']

    def test_2025_record_imports_with_its_achievements_and_conducts(self):
        old_achievements, old_conducts = bit_positions(
            OLD_FORMATS[2025]['fixtures'])
        values = {'conduct': 0, 'achieve': 1 << 13 | 1 << 14}
        for define in ('A_IDENTIFIED_ALL_WANDS', 'A_NPC_DEATHMATCH',
                       'A_DID_PURE_SOKOBAN', 'A_FOUND_MINES_ALTAR',
                       'A_CROWNED', 'A_REACHED_LEVEL_30',
                       'A_EXPELLED_FROM_QUEST'):
            field, bit = old_achievements[define]
            values[field] = values.get(field, 0) | 1 << bit
        for shortname in ('food', 'elbe', 'pets', 'deaf'):
            field, bit = old_conducts[shortname]
            values[field] |= 1 << bit
        start = in_window()
        record = [
            'server=us.hardfought.org', 'version=3.6.7', 'points=1773',
            # robotfindskitten, which the current game numbers differently
            'deathdnum=8', 'deathlev=5', 'maxlvl=10', 'hp=0', 'maxhp=65',
            'deaths=1', 'deathdate=20251101', 'birthdate=20251101',
            'uid=5', 'role=Val', 'race=Dwa', 'gender=Fem', 'align=Law',
            'name=alice', 'death=killed by a gold golem',
            'conduct=0x%x' % values['conduct'], 'turns=1904',
            'achieve=0x%x' % values['achieve'], 'realtime=634',
            'starttime=%d' % start, 'endtime=%d' % (start + 634),
            'gender0=Fem', 'align0=Law', 'flags=0x4',
        ] + ['tnntachieve%d=0x%x' % (i, values.get('tnntachieve%d' % i, 0))
             for i in range(6)]

        converter = RecordConverter(OLD_FORMATS[2025], (old_achievements,
                                                        old_conducts),
                                    bit_positions())
        entry = parse_xlog_line('\t'.join(converter.convert(record)))
        self.assertEqual(game_from_xlog(Source.objects.get(server='hdf'),
                                        entry), ADDED)
        game = Game.objects.get()
        self.assertEqual(game.version, '5.0.0')
        self.assertEqual(
            set(game.achievements.values_list('define', flat=True)),
            {'A_IDENTIFIED_ALL_WANDS', 'A_NPC_DEATHMATCH',
             'A_COMPLETED_PURE_SOKOBAN', 'A_ENTERED_MINETOWN',
             'A_GOT_CROWNED'})
        self.assertEqual(
            set(game.conducts.values_list('shortname', flat=True)),
            {'food', 'elbe', 'pets', 'deaf', 'nude'})
