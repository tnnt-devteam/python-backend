"""
Clan invitations are capped: a clan's members plus its pending invitations
may not exceed MAX_CLAN_PLAYERS, so every invitation can be accepted.
Joining or creating a clan withdraws a player's other invitations, which
gives those clans their places back.
"""
from datetime import datetime, timedelta, timezone
from unittest import mock

from django.test import Client, TestCase

import tnnt.settings
from scoreboard.models import Clan, Player
from scoreboard.tests.test_views import login_player
from tnnt import hardfought_utils

MAX = 4  # MAX_CLAN_PLAYERS in these tests


class InviteCapTests(TestCase):

    def setUp(self):
        now = datetime.now(tz=timezone.utc)
        for name, value in (
                ('MAX_CLAN_PLAYERS', MAX),
                ('CLAN_FREEZE_TIME', None),
                ('TOURNAMENT_END', now + timedelta(days=30))):
            patcher = mock.patch.object(tnnt.settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(hardfought_utils, 'DGL_DATABASE_PATH',
                                    'dgamelaunch_test.db')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.clan = Clan.objects.create(name='Testers')
        self.admin = login_player(self.client, 'zed', self.clan, admin=True)

    def invite(self, name):
        return self.client.post('/clanmgmt', {'invite': '', 'invitee': name})

    def add_members(self, count):
        for i in range(count):
            Player.objects.create(name='member%d' % i, clan=self.clan)

    def add_invites(self, *names):
        for name in names:
            player, _ = Player.objects.get_or_create(name=name)
            player.invites.add(self.clan)

    def test_places_are_shown(self):
        self.add_members(1)
        self.add_invites('bob')
        resp = self.client.get('/clanmgmt')
        self.assertEqual(resp.context['clan_places'],
                         {'members': 2, 'invites': 1, 'used': 3, 'max': MAX,
                          'free': 1})
        self.assertContains(resp, 'Places used: 3 of 4')
        self.assertContains(resp, 'name="invitee"')

    def test_invites_stop_at_the_free_places(self):
        self.add_members(1)
        for name in ('bob', 'chuck'):
            Player.objects.create(name=name)
            resp = self.invite(name)
            self.assertNotIn('errmsg', resp.context)
        resp = self.invite('gimli')  # in the dgl database, not a Player yet
        self.assertIn('no free places', resp.context['errmsg'])
        # refused before find_player could create a Player row
        self.assertFalse(Player.objects.filter(name='gimli').exists())
        self.assertEqual(self.clan.invitees.count(), 2)
        self.assertContains(resp, 'Rescind an invitation to invite')
        self.assertNotContains(resp, 'name="invitee"')

    def test_a_full_clan_says_so(self):
        self.add_members(MAX - 1)
        Player.objects.create(name='bob')
        resp = self.invite('bob')
        self.assertEqual(resp.context['errmsg'], 'Your clan is full')
        self.assertContains(resp, 'Your clan is full.')
        self.assertNotContains(resp, 'name="invitee"')
        self.assertEqual(self.clan.invitees.count(), 0)

    def test_reinviting_takes_no_place(self):
        self.add_members(1)
        self.add_invites('bob', 'chuck')
        resp = self.invite('bob')
        self.assertNotIn('errmsg', resp.context)
        self.assertEqual(self.clan.invitees.count(), 2)

    def test_a_member_cannot_be_invited(self):
        self.add_members(1)
        resp = self.invite('member0')
        self.assertEqual(resp.context['errmsg'],
                         'member0 is already in your clan')
        self.assertEqual(self.clan.invitees.count(), 0)

    def test_rescinding_frees_a_place(self):
        self.add_members(1)
        self.add_invites('bob', 'chuck')
        Player.objects.create(name='dave')
        self.assertIn('no free places', self.invite('dave').context['errmsg'])
        self.client.post('/clanmgmt', {
            'rescind': '', 'rescind_id': Player.objects.get(name='bob').id})
        resp = self.invite('dave')
        self.assertNotIn('errmsg', resp.context)
        self.assertEqual(
            sorted(p.name for p in self.clan.invitees.all()),
            ['chuck', 'dave'])

    def test_joining_withdraws_other_invitations(self):
        other = Clan.objects.create(name='Others')
        bob_client = Client()
        bob = login_player(bob_client, 'bob')
        bob.invites.add(self.clan, other)
        self.add_members(1)
        self.add_invites('chuck')
        self.assertEqual(
            self.client.get('/clanmgmt').context['clan_places']['free'], 0)
        bob_client.post('/clanmgmt',
                        {'join_clan': '', 'join_clan_id': other.id})
        bob.refresh_from_db()
        self.assertEqual(bob.clan, other)
        self.assertEqual(bob.invites.count(), 0)
        # Testers gets bob's place back
        self.assertEqual(
            self.client.get('/clanmgmt').context['clan_places']['free'], 1)

    def test_creating_a_clan_withdraws_invitations(self):
        bob_client = Client()
        bob = login_player(bob_client, 'bob')
        bob.invites.add(self.clan)
        bob_client.post('/clanmgmt',
                        {'create_clan': '', 'clan_name': 'Bobs'})
        bob.refresh_from_db()
        self.assertEqual(bob.clan.name, 'Bobs')
        self.assertEqual(bob.invites.count(), 0)
        self.assertEqual(self.clan.invitees.count(), 0)

    def test_looking_for_clan_invite_buttons_follow_the_places(self):
        Player.objects.create(name='alice', looking_for_clan=True)
        self.add_members(1)
        self.add_invites('bob')
        button = 'name="invitee" type="hidden" value="alice"'
        self.assertContains(self.client.get('/clanmgmt'), button)
        self.add_invites('chuck')
        resp = self.client.get('/clanmgmt')
        self.assertContains(resp, 'alice')
        self.assertNotContains(resp, button)

    def test_joining_is_still_refused_when_full(self):
        # a clan over the cap from before it existed keeps its invitations,
        # and the join-time check still stops it growing past the size cap
        self.add_members(MAX - 1)
        bob_client = Client()
        bob = login_player(bob_client, 'bob')
        bob.invites.add(self.clan)
        resp = bob_client.post('/clanmgmt',
                               {'join_clan': '', 'join_clan_id': self.clan.id})
        self.assertEqual(resp.context['errmsg'], 'That clan is full')
        bob.refresh_from_db()
        self.assertIsNone(bob.clan)
