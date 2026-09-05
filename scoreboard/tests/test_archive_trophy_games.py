"""
Tests for the archive_trophy_games management command, which writes the
static per-player / per-clan game lists an archived trophy grid reads.
"""
import json
import os
import shutil
import tempfile
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from scoreboard.models import Clan, Player, Source
from scoreboard.tests.test_aggregate import make_game


def dumplog(game):
    return game.source.dumplog_fmt.replace('%n1', game.player.name[0]) \
        .replace('%n', game.player.name) \
        .replace('%st', str(int(game.starttime.timestamp())))


class ArchiveTrophyGamesTests(TestCase):
    fixtures = ['sources']

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.src = Source.objects.get(server='hfe')

    def run_command(self, **kwargs):
        out = StringIO()
        kwargs.setdefault('archive_dir', self.tmp)
        call_command('archive_trophy_games', '2025', stdout=out, **kwargs)
        return out.getvalue()

    def read(self, entity_type, name):
        path = os.path.join(self.tmp, 'api', 'trophy-grid-games',
                            entity_type, name + '.json')
        with open(path, encoding='utf-8') as infile:
            return json.load(infile)

    def test_player_file_groups_games_by_combo_and_section(self):
        alice = Player.objects.create(name='alice')
        both = make_game(alice, self.src, gender0='Mal', won=True,
                         mines_soko=True)
        asc_only = make_game(alice, self.src, gender0='Fem', won=True,
                             mines_soko=False)
        # a plain death is in no section, so its combo is not listed
        make_game(alice, self.src, role='Sam', race='Hum', align0='Law',
                  won=False, mines_soko=False, death='killed by a newt')
        # and a different combo gets its own key
        other = make_game(alice, self.src, role='Wiz', race='Elf',
                          align0='Cha', gender0='Fem', won=False,
                          mines_soko=True, death='killed by a soldier ant')

        output = self.run_command()

        self.assertIn('Wrote 1 player and 0 clan game files', output)
        data = self.read('player', 'alice')
        self.assertEqual(data['entity_type'], 'player')
        self.assertEqual(data['name'], 'alice')
        self.assertEqual(set(data['combos']), {'Val-Hum-Law', 'Wiz-Elf-Cha'})

        combo = data['combos']['Val-Hum-Law']
        self.assertEqual(set(combo), {'mines_soko', 'male_ascensions',
                                      'female_ascensions'})
        self.assertEqual([g['dumplog'] for g in combo['mines_soko']],
                         [dumplog(both)])
        self.assertEqual([g['dumplog'] for g in combo['male_ascensions']],
                         [dumplog(both)])
        self.assertEqual([g['dumplog'] for g in combo['female_ascensions']],
                         [dumplog(asc_only)])

        wiz = data['combos']['Wiz-Elf-Cha']
        self.assertEqual([g['dumplog'] for g in wiz['mines_soko']],
                         [dumplog(other)])
        self.assertEqual(wiz['male_ascensions'], [])
        self.assertEqual(wiz['female_ascensions'], [])

    def test_entry_fields_match_the_live_api(self):
        alice = Player.objects.create(name='alice')
        game = make_game(alice, self.src, gender0='Fem', won=True,
                         mines_soko=False, points=1234567, turns=31337)
        self.run_command()
        entry = self.read('player', 'alice')['combos']['Val-Hum-Law'][
            'female_ascensions'][0]
        self.assertEqual(entry, {
            'player__name': 'alice',
            'endtime': game.endtime.strftime('%Y-%m-%d %H:%M'),
            'points': 1234567,
            'turns': 31337,
            'dumplog': 'https://eu.hardfought.org/userdata/a/alice/tnnt/'
                       'dumplog/%d.tnnt.html'
                       % int(game.starttime.timestamp()),
        })

    def test_lists_are_newest_first(self):
        alice = Player.objects.create(name='alice')
        first = make_game(alice, self.src, gender0='Mal', won=True)
        second = make_game(alice, self.src, gender0='Mal', won=True,
                           start=first.starttime + timedelta(days=2))
        self.run_command()
        males = self.read('player', 'alice')['combos']['Val-Hum-Law'][
            'male_ascensions']
        self.assertEqual([g['dumplog'] for g in males],
                         [dumplog(second), dumplog(first)])

    def test_clan_file_holds_current_members_games_only(self):
        clan = Clan.objects.create(name='Clan EIT!')
        bob = Player.objects.create(name='bob', clan=clan)
        carol = Player.objects.create(name='carol', clan=clan)
        Player.objects.create(name='dave')  # not a member
        make_game(bob, self.src, gender0='Mal', won=True)
        make_game(carol, self.src, gender0='Fem', won=True)
        make_game(Player.objects.get(name='dave'), self.src, gender0='Mal',
                  won=True)

        output = self.run_command()

        self.assertIn('Wrote 3 player and 1 clan game files', output)
        data = self.read('clan', 'Clan EIT!')
        self.assertEqual(data['entity_type'], 'clan')
        self.assertEqual(data['name'], 'Clan EIT!')
        combo = data['combos']['Val-Hum-Law']
        self.assertEqual([g['player__name'] for g in combo['male_ascensions']],
                         ['bob'])
        self.assertEqual([g['player__name'] for g in
                          combo['female_ascensions']], ['carol'])
        # each member's own file is unaffected by the clan
        self.assertEqual(list(self.read('player', 'carol')['combos'][
            'Val-Hum-Law']['male_ascensions']), [])

    def test_entity_without_games_gets_an_empty_file(self):
        # an invited player who never played still has an archived page
        Player.objects.create(name='erin')
        Clan.objects.create(name='Quiet')
        self.run_command()
        self.assertEqual(self.read('player', 'erin')['combos'], {})
        self.assertEqual(self.read('clan', 'Quiet')['combos'], {})

    def test_name_that_cannot_be_a_file_is_skipped_with_a_warning(self):
        Clan.objects.create(name='a/b')
        Clan.objects.create(name='fine')
        with self.assertLogs(level='WARNING') as logs:
            output = self.run_command()
        self.assertIn("skipping clan 'a/b'", logs.output[0])
        self.assertIn('Wrote 0 player and 1 clan game files', output)
        self.assertEqual(self.read('clan', 'fine')['combos'], {})
        self.assertFalse(os.path.exists(os.path.join(
            self.tmp, 'api', 'trophy-grid-games', 'clan', 'a')))

    def test_missing_archive_dir_is_an_error(self):
        with self.assertRaises(CommandError) as cm:
            self.run_command(archive_dir=os.path.join(self.tmp, 'nope'))
        self.assertIn('archive_tournament.sh 2025', str(cm.exception))

    def test_bad_year_is_an_error(self):
        with self.assertRaises(CommandError):
            call_command('archive_trophy_games', '25', archive_dir=self.tmp)
