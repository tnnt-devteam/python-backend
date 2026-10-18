"""
Tests for the test_mode management command, the database half of
test_mode.sh: on loads the test xlogfiles and turns logins and clan
operations on, off deletes whatever test mode created.
"""
import json
import tempfile
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import User
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

import tnnt.settings
from scoreboard.models import Clan, Game, Player, SiteSettings, Source
from scoreboard.tests.helpers import xlog_line
from scoreboard.tests.test_aggregate import make_game

# The tournament these tests pretend is coming up...
LIVE_START = datetime(2030, 11, 1, tzinfo=timezone.utc)
LIVE_END = datetime(2030, 12, 1, tzinfo=timezone.utc)
# ...and a moment during the one before it
LAST_YEAR = int(datetime(2029, 11, 5, tzinfo=timezone.utc).timestamp())


class TestModeTests(TestCase):
    fixtures = ['conducts', 'achievements', 'sources', 'trophies']

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.state = self.dir / 'state.json'
        for name, value in (('TOURNAMENT_START', LIVE_START),
                            ('TOURNAMENT_END', LIVE_END),
                            ('DONOR_FILES', []),
                            ('TEMP_ACHIEVEMENTS_PATH', None),
                            ('BASE_DIR', self.dir)):
            patcher = mock.patch.object(tnnt.settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for server, names in (('us', ('alice', 'bob')), ('eu', ('eve',)),
                              ('au', ('janet',))):
            (self.dir / ('test-%s.xlog' % server)).write_text(''.join(
                xlog_line(name=name, server='%s.hardfought.org' % server,
                          start=LAST_YEAR + 3600 * i)
                for i, name in enumerate(names)))

        # what the live database holds off-season: an admin's login, and
        # logins and clan operations switched off
        self.admin = User.objects.create(username='k2')
        self.admin_player = Player.objects.create(name='k2', user=self.admin)
        site = SiteSettings.load()
        site.login_enabled = False
        site.clan_operations_enabled = False
        site.updated_by = 'k2'
        site.save()

    def run_command(self, *args):
        out = StringIO()
        call_command('test_mode', *args, '--state', str(self.state),
                     stdout=out, stderr=StringIO())
        return out.getvalue()

    def assert_untouched(self):
        self.assertEqual(Game.objects.count(), 0)
        self.assertEqual(sorted(Player.objects.values_list('name',
                                                           flat=True)),
                         ['k2'])
        self.assertEqual(list(User.objects.values_list('username',
                                                       flat=True)), ['k2'])
        site = SiteSettings.load()
        self.assertFalse(site.login_enabled)
        self.assertFalse(site.clan_operations_enabled)
        self.assertEqual(site.updated_by, 'k2')

    def test_on_loads_the_games_and_turns_the_switches_on(self):
        out = self.run_command('on', '--backup', '/root/backup.sql.gz')
        self.assertIn('Test mode on', out)
        self.assertEqual(Game.objects.count(), 4)
        site = SiteSettings.load()
        self.assertTrue(site.login_enabled)
        self.assertTrue(site.clan_operations_enabled)
        self.assertEqual(site.updated_by, 'test_mode')
        state = json.loads(self.state.read_text())
        self.assertEqual(state['backup'], '/root/backup.sql.gz')
        self.assertEqual(state['max_ids']['player'], self.admin_player.id)
        self.assertEqual(state['max_ids']['game'], 0)
        self.assertEqual(state['site_settings'], {
            'login_enabled': False, 'clan_operations_enabled': False,
            'updated_by': 'k2'})

    def test_on_dry_run_logs_in_and_changes_nothing(self):
        out = self.run_command('on', '--dry-run')
        self.assertIn('test-us.xlog: 2 added', out)
        self.assertIn('Logged in as alice', out)
        self.assertIn('rolled back', out)
        self.assertFalse(self.state.exists())
        self.assert_untouched()
        self.assertEqual(Session.objects.count(), 0)

    def test_on_refuses_twice_and_with_old_games_present(self):
        self.run_command('on')
        with self.assertRaises(CommandError):
            self.run_command('on')
        self.state.unlink()
        with self.assertRaises(CommandError):
            self.run_command('on')
        self.assertFalse(self.state.exists())

    def test_failed_on_leaves_no_state_file(self):
        (self.dir / 'test-au.xlog').unlink()
        with self.assertRaises(CommandError):
            self.run_command('on')
        self.assertFalse(self.state.exists())
        self.assert_untouched()

    def act_as_test_players(self):
        """
        What test players can do on the site, plus a real tournament game
        that arrives while the site is in test mode.
        """
        alice = Player.objects.get(name='alice')
        alice.user = User.objects.create(username='alice')
        clan = Clan.objects.create(name='TestClan')
        alice.clan = clan
        alice.save()
        # an invite creates a Player for any name, and can name a real one
        Player.objects.create(name='stranger').invites.add(clan)
        self.admin_player.invites.add(clan)
        session = SessionStore()
        session['_auth_user_id'] = str(alice.user.id)
        session.create()
        make_game(Player.objects.create(name='realguy'),
                  Source.objects.get(server='hdf'),
                  start=LIVE_START + timedelta(days=1))

    def test_off_deletes_what_test_mode_created(self):
        self.run_command('on')
        self.act_as_test_players()
        out = self.run_command('off')
        self.assertIn('Deleted 1 clans, 4 games', out)
        self.assertIn('Kept 1 players with tournament games', out)
        self.assertEqual(sorted(Player.objects.values_list('name',
                                                           flat=True)),
                         ['k2', 'realguy'])
        self.assertEqual(Game.objects.get().player.name, 'realguy')
        self.assertFalse(Clan.objects.exists())
        self.assertFalse(self.admin_player.invites.exists())
        self.assertEqual(list(User.objects.values_list('username',
                                                       flat=True)), ['k2'])
        self.assertFalse(Session.objects.exists())
        site = SiteSettings.load()
        self.assertFalse(site.login_enabled)
        self.assertFalse(site.clan_operations_enabled)
        self.assertEqual(site.updated_by, 'k2')
        self.assertFalse(self.state.exists())
        self.assertEqual(len(list(self.dir.glob('state.json.reverted-*'))),
                         1)

    def test_off_dry_run_changes_nothing(self):
        self.run_command('on')
        self.act_as_test_players()
        out = self.run_command('off', '--dry-run')
        self.assertIn('Would delete 1 clans, 4 games', out)
        self.assertIn('rolled back', out)
        self.assertTrue(self.state.exists())
        self.assertEqual(Game.objects.count(), 5)
        self.assertTrue(Clan.objects.exists())
        self.assertEqual(Session.objects.count(), 1)
        self.assertTrue(SiteSettings.load().login_enabled)

    def test_off_needs_a_state_file(self):
        with self.assertRaises(CommandError):
            self.run_command('off')
        self.state.write_text('{"max_ids": {}}')
        with self.assertRaises(CommandError):
            self.run_command('off')

    def test_status(self):
        self.assertIn('Not in test mode', self.run_command('status'))
        self.run_command('on')
        out = self.run_command('status')
        self.assertIn('login_enabled=True', out)
        self.assertIn('In test mode since', out)
