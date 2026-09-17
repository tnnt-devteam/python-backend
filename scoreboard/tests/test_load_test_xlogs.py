"""
Tests for the load_test_xlogs management command, which imports the test
xlogfiles (games from an earlier tournament) and removes them again.
"""
import tempfile
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

import tnnt.settings
from scoreboard.management.commands import load_test_xlogs
from scoreboard.models import Achievement, Clan, Game, Player, Source
from scoreboard.tests.helpers import xlog_line
from scoreboard.tests.test_aggregate import make_game

# The tournament these tests pretend is coming up...
LIVE_START = datetime(2030, 11, 1, tzinfo=timezone.utc)
LIVE_END = datetime(2030, 12, 1, tzinfo=timezone.utc)
# ...and a moment during the one before it
LAST_YEAR = int(datetime(2029, 11, 5, tzinfo=timezone.utc).timestamp())


def at(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc)


class LoadTestXlogsTests(TestCase):
    fixtures = ['conducts', 'achievements', 'sources', 'trophies']

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        for name, value in (('TOURNAMENT_START', LIVE_START),
                            ('TOURNAMENT_END', LIVE_END),
                            ('DONOR_FILES', []),
                            ('TEMP_ACHIEVEMENTS_PATH', None),
                            ('BASE_DIR', self.dir)):
            patcher = mock.patch.object(tnnt.settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        eu = 'eu.hardfought.org'
        self.us = self.write('test-us.xlog', [
            xlog_line(name='alice', start=LAST_YEAR),
            xlog_line(name='alice', start=LAST_YEAR + 3600),
            xlog_line(name='bob', start=LAST_YEAR + 7200),
            xlog_line(name='chuck', start=LAST_YEAR + 10800),
        ])
        self.eu = self.write('test-eu.xlog', [
            xlog_line(name='david', server=eu, start=LAST_YEAR),
            xlog_line(name='eve', server=eu, start=LAST_YEAR + 3600),
            xlog_line(name='gimli', server=eu, start=LAST_YEAR + 7200),
        ])
        self.src = Source.objects.get(server='hdf')

    def write(self, filename, lines):
        path = self.dir / filename
        path.write_text(''.join(lines))
        return str(path)

    def run_command(self, *args, **kwargs):
        out = StringIO()
        call_command('load_test_xlogs', *args, stdout=out, **kwargs)
        return out.getvalue()

    def test_load_imports_the_games_and_aggregates(self):
        out = self.run_command(self.us, self.eu)
        self.assertIn('test-us.xlog: 4 added, 0 filtered, 0 duplicates, '
                      '0 bad', out)
        self.assertIn('test-eu.xlog: 3 added', out)
        self.assertEqual(Game.objects.count(), 7)
        # the source comes from each record's server field
        self.assertEqual(Game.objects.get(player__name='david').source.server,
                         'hfe')
        self.assertEqual(Player.objects.get(name='alice').total_games, 2)
        # the live window is back in place
        self.assertEqual(tnnt.settings.TOURNAMENT_START, LIVE_START)
        self.assertEqual(tnnt.settings.TOURNAMENT_END, LIVE_END)

    def test_default_files_and_year(self):
        self.write('test-au.xlog', [
            xlog_line(name='janet', server='au.hardfought.org',
                      start=LAST_YEAR),
            # from two tournaments ago: outside the default year
            xlog_line(name='janet', server='au.hardfought.org',
                      start=LAST_YEAR - 366 * 86400),
        ])
        out = self.run_command()
        for name in load_test_xlogs.TEST_FILES:
            self.assertIn(str(self.dir / name), out)
        self.assertIn('test-au.xlog: 1 added, 1 filtered', out)
        self.assertEqual(Game.objects.count(), 8)

    def test_loading_twice_only_finds_duplicates(self):
        self.run_command(self.us)
        out = self.run_command(self.us)
        self.assertIn('0 added, 0 filtered, 4 duplicates, 0 bad', out)
        self.assertEqual(Game.objects.count(), 4)

    def test_window_is_restored_when_an_import_fails(self):
        with mock.patch.object(load_test_xlogs, 'import_from_file',
                               side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                self.run_command(self.us)
        self.assertEqual(tnnt.settings.TOURNAMENT_START, LIVE_START)
        self.assertEqual(tnnt.settings.TOURNAMENT_END, LIVE_END)

    def test_refused_while_the_tournament_is_on(self):
        now = datetime.now(timezone.utc)
        with mock.patch.object(tnnt.settings, 'TOURNAMENT_START',
                               now - timedelta(days=1)), \
                mock.patch.object(tnnt.settings, 'TOURNAMENT_END',
                                  now + timedelta(days=1)):
            with self.assertRaisesMessage(CommandError,
                                          'the tournament is on'):
                self.run_command(self.us)
        self.assertFalse(Game.objects.exists())

    def test_refused_while_tournament_games_are_in_the_database(self):
        carol = Player.objects.create(name='carol')
        make_game(carol, self.src, start=LIVE_START + timedelta(days=1))
        with self.assertRaisesMessage(CommandError,
                                      'holds games from the 2030'):
            self.run_command(self.us)
        self.assertEqual(Game.objects.count(), 1)

    def test_refused_for_a_year_that_reaches_the_tournament(self):
        with self.assertRaisesMessage(CommandError, 'do not end before'):
            self.run_command(self.us, year=2030)
        self.assertFalse(Game.objects.exists())

    def test_missing_file_is_refused_before_anything_is_imported(self):
        with self.assertRaisesMessage(CommandError, 'no such file'):
            self.run_command(self.us, str(self.dir / 'missing.xlog'))
        self.assertFalse(Game.objects.exists())

    def test_option_mixups_are_refused(self):
        with self.assertRaisesMessage(CommandError, '--dry-run only'):
            self.run_command(self.us, dry_run=True)
        with self.assertRaisesMessage(CommandError, '--year only'):
            self.run_command(self.us, remove=True, year=2029)

    def test_remove_spares_tournament_games_and_linked_players(self):
        self.run_command(self.us, self.eu)
        # alice has played in the tournament since
        alice = Player.objects.get(name='alice')
        kept_game = make_game(alice, self.src,
                              start=LIVE_START + timedelta(days=1))
        # bob has logged in, chuck is in a clan, david has an invite and
        # gimli has a game in progress
        bob = Player.objects.get(name='bob')
        bob.user = User.objects.create(username='bob')
        bob.save()
        clan = Clan.objects.create(name='Testers')
        Player.objects.filter(name='chuck').update(clan=clan)
        Player.objects.get(name='david').invites.add(clan)
        Player.objects.get(name='gimli').temp_achievements.add(
            Achievement.objects.first())
        # the files don't name carol, so her early game stays
        carol = Player.objects.create(name='carol')
        other_game = make_game(carol, self.src, start=at(LAST_YEAR))

        out = self.run_command(self.us, self.eu, remove=True)

        self.assertIn('Deleted 7 games', out)
        self.assertIn('and 1 players', out)
        self.assertIn('restart tnntbot', out.lower())
        self.assertEqual(set(Game.objects.values_list('id', flat=True)),
                         {kept_game.id, other_game.id})
        self.assertEqual(
            set(Player.objects.values_list('name', flat=True)),
            {'alice', 'bob', 'chuck', 'david', 'gimli', 'carol'})
        self.assertEqual(Player.objects.get(name='alice').total_games, 1)

    def test_dry_run_deletes_nothing(self):
        self.run_command(self.us, self.eu)
        out = self.run_command(self.us, self.eu, remove=True, dry_run=True)
        self.assertIn('Would delete 7 games', out)
        self.assertIn('and 6 players', out)
        self.assertEqual(Game.objects.count(), 7)
        self.assertEqual(Player.objects.count(), 6)
