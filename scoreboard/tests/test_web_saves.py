"""
The website's saves of existing Player and Clan rows write only the fields
they change (2026-11-01). aggregate rewrites every row's stats every 5
minutes; a whole-row save of the copy a request loaded before aggregate
committed would put the old stats back until the next run. (aggregate's
own saves name their fields too, since eb4c318.)
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase

import tnnt.settings
from scoreboard.models import Clan, Player
from scoreboard.tests.test_views import TEST_DGL_DB, login_player
from tnnt import hardfought_utils

NEW_STATS = {'wins': 7, 'total_games': 9}


@contextmanager
def aggregate_commits_first():
    """
    Run every save of an existing Player or Clan row right after an
    aggregate run committed new stats for that row.
    """
    real = {Player: Player.save, Clan: Clan.save}

    def racing(model):
        def save(self, *args, **kwargs):
            if self.pk is not None:
                model.objects.filter(pk=self.pk).update(**NEW_STATS)
            return real[model](self, *args, **kwargs)
        return save
    with mock.patch.object(Player, 'save', racing(Player)), \
            mock.patch.object(Clan, 'save', racing(Clan)):
        yield


class WebSavesKeepStatsTests(TestCase):

    def setUp(self):
        now = datetime.now(tz=timezone.utc)
        for name, value in (('CLAN_FREEZE_TIME', now + timedelta(days=1)),
                            ('TOURNAMENT_END', now + timedelta(days=30))):
            patcher = mock.patch.object(tnnt.settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(hardfought_utils, 'DGL_DATABASE_PATH',
                                    TEST_DGL_DB)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.clan = Clan.objects.create(name='Testers')

    def assertStatsKept(self, obj):
        obj.refresh_from_db()
        self.assertEqual((obj.wins, obj.total_games), (7, 9))

    def post(self, data, path='/clanmgmt'):
        with aggregate_commits_first():
            return self.client.post(path, data)

    def test_create_clan(self):
        bob = login_player(self.client, 'bob')
        self.post({'create_clan': '', 'clan_name': 'Combo Crew'})
        self.assertStatsKept(bob)
        self.assertEqual(bob.clan.name, 'Combo Crew')
        self.assertTrue(bob.clan_admin)

    def test_join_clan(self):
        bob = login_player(self.client, 'bob')
        bob.invites.add(self.clan)
        self.post({'join_clan': '', 'join_clan_id': self.clan.id})
        self.assertStatsKept(bob)
        self.assertEqual(bob.clan, self.clan)

    def test_leave_clan(self):
        Player.objects.create(name='zed', clan=self.clan, clan_admin=True)
        bob = login_player(self.client, 'bob', self.clan)
        self.post({'leave': ''})
        self.assertStatsKept(bob)
        self.assertIsNone(bob.clan)

    def test_kick_member(self):
        login_player(self.client, 'zed', self.clan, admin=True)
        bob = Player.objects.create(name='bob', clan=self.clan)
        self.post({'kick': '', 'kick_or_admin_id': bob.id})
        self.assertStatsKept(bob)
        self.assertIsNone(bob.clan)

    def test_make_admin(self):
        login_player(self.client, 'zed', self.clan, admin=True)
        bob = Player.objects.create(name='bob', clan=self.clan)
        self.post({'adminify': '', 'kick_or_admin_id': bob.id})
        self.assertStatsKept(bob)
        self.assertTrue(bob.clan_admin)

    def test_disband_clan(self):
        zed = login_player(self.client, 'zed', self.clan, admin=True)
        bob = Player.objects.create(name='bob', clan=self.clan)
        self.post({'disband': ''})
        for member in (zed, bob):
            self.assertStatsKept(member)
            self.assertIsNone(member.clan)
        self.assertFalse(Clan.objects.filter(pk=self.clan.pk).exists())

    def test_set_clan_message(self):
        login_player(self.client, 'zed', self.clan, admin=True)
        self.post({'set_message': '', 'message': 'recruiting'})
        self.assertStatsKept(self.clan)
        self.assertEqual(self.clan.message, 'recruiting')

    def test_set_looking_for_clan(self):
        bob = login_player(self.client, 'bob')
        self.post({'set_lfc': '', 'looking_for_clan': 'on',
                   'lfc_message': 'tank for hire'})
        self.assertStatsKept(bob)
        self.assertTrue(bob.looking_for_clan)
        self.assertEqual(bob.lfc_message, 'tank for hire')

    def test_admin_clears_looking_for_clan(self):
        login_player(self.client, 'k2')  # in SITE_ADMINS
        bob = Player.objects.create(name='bob', looking_for_clan=True,
                                    lfc_message='spam')
        self.post({'clear_lfc': '', 'lfc_player_id': bob.id},
                  path='/admin-panel')
        self.assertStatsKept(bob)
        self.assertFalse(bob.looking_for_clan)
        self.assertEqual(bob.lfc_message, '')

    def test_user_linked_to_its_player_on_a_page_load(self):
        # get_player()'s fallback: a User with no linked Player is linked
        # to the Player of the same name
        bob = Player.objects.create(name='bob')
        self.client.force_login(User.objects.create_user('bob'))
        with aggregate_commits_first():
            self.client.get('/clanmgmt')
        self.assertStatsKept(bob)
        self.assertEqual(bob.user.username, 'bob')

    def test_user_linked_to_its_player_at_first_login(self):
        # the Player exists already (an invitation creates one); the first
        # login creates the User and links it
        alice = Player.objects.create(name='alice')
        with aggregate_commits_first():
            user = hardfought_utils.HdfAuthBackend().authenticate(
                None, username='alice', password='alice')
        self.assertIsNotNone(user)
        self.assertStatsKept(alice)
        self.assertEqual(alice.user, user)
