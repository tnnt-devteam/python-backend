"""
Looking For Clan: a clanless player flags themself, with an optional
message, on /clanmgmt. While clans can still be joined the flag shows on
their player page, in the public list on /clans and, with invite buttons,
to clan admins on /clanmgmt. Site admins can clear it on /admin-panel.
"""
from datetime import datetime, timedelta, timezone
from unittest import mock

from django.test import TestCase

import tnnt.settings
from scoreboard.models import Clan, Player, SiteSettings
from scoreboard.tests.test_views import login_player
from tnnt import hardfought_utils

DISCLAIMER = ('This will be visible to everyone on your profile page and '
              'on the Clans page.')


def set_lfc(client, looking=True, message=''):
    data = {'set_lfc': '', 'lfc_message': message}
    if looking:
        data['looking_for_clan'] = 'on'
    return client.post('/clanmgmt', data)


class LookingForClanTestCase(TestCase):
    """Clans are joinable: clan freeze and the tournament end are ahead."""

    def setUp(self):
        now = datetime.now(tz=timezone.utc)
        self.patch_times(freeze=now + timedelta(days=1),
                         end=now + timedelta(days=30))

    def patch_times(self, freeze, end):
        for name, value in (('CLAN_FREEZE_TIME', freeze),
                            ('TOURNAMENT_END', end)):
            patcher = mock.patch.object(tnnt.settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def close_clans(self):
        self.patch_times(
            freeze=datetime.now(tz=timezone.utc) - timedelta(minutes=1),
            end=datetime.now(tz=timezone.utc) + timedelta(days=30))


class SetFlagTests(LookingForClanTestCase):

    def setUp(self):
        super().setUp()
        self.alice = login_player(self.client, 'alice')

    def test_form_and_disclaimer_shown_to_clanless_player(self):
        resp = self.client.get('/clanmgmt')
        self.assertContains(resp, 'name="set_lfc"')
        self.assertContains(resp, 'This will be visible to everyone on your')
        self.assertFalse(resp.context['lfc_form']['looking_for_clan'].value())

    def test_set_and_clear(self):
        resp = set_lfc(self.client, message='I am a conducts specialist!')
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('errmsg', resp.context)
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.looking_for_clan)
        self.assertEqual(self.alice.lfc_message,
                         'I am a conducts specialist!')
        # the form shows the saved state
        self.assertTrue(resp.context['lfc_form']['looking_for_clan'].value())
        self.assertContains(resp, 'You are flagged as looking for a clan')

        set_lfc(self.client, looking=False,
                message='I am a conducts specialist!')
        self.alice.refresh_from_db()
        self.assertFalse(self.alice.looking_for_clan)

    def test_message_is_optional(self):
        set_lfc(self.client)
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.looking_for_clan)
        self.assertEqual(self.alice.lfc_message, '')

    def test_invalid_messages_are_refused(self):
        for bad in ('x' * 201, 'bad\x01msg', 'emoji \U0001F600'):
            resp = set_lfc(self.client, message=bad)
            self.assertIn('lfc_message', resp.context['lfc_form'].errors)
        self.alice.refresh_from_db()
        self.assertFalse(self.alice.looking_for_clan)
        self.assertEqual(self.alice.lfc_message, '')

    def test_refused_while_clan_operations_are_disabled(self):
        SiteSettings.objects.create(clan_operations_enabled=False)
        with self.assertLogs(level='WARNING'):
            resp = set_lfc(self.client, message='hi')
        self.assertIn('disabled', resp.context['errmsg'])
        self.alice.refresh_from_db()
        self.assertFalse(self.alice.looking_for_clan)

    def test_refused_and_hidden_during_clan_freeze(self):
        self.close_clans()
        self.assertNotContains(self.client.get('/clanmgmt'), 'set_lfc')
        with self.assertLogs(level='WARNING'):
            resp = set_lfc(self.client, message='hi')
        self.assertEqual(resp.context['errmsg'],
                         'You can no longer look for a clan')
        self.alice.refresh_from_db()
        self.assertFalse(self.alice.looking_for_clan)

    def test_refused_in_a_clan(self):
        self.alice.clan = Clan.objects.create(name='Testers')
        self.alice.save()
        self.assertNotContains(self.client.get('/clanmgmt'), 'set_lfc')
        with self.assertLogs(level='WARNING'):
            resp = set_lfc(self.client, message='hi')
        self.assertIn('already in one', resp.context['errmsg'])
        self.alice.refresh_from_db()
        self.assertFalse(self.alice.looking_for_clan)

    def test_creating_a_clan_clears_the_flag(self):
        set_lfc(self.client, message='hi')
        self.client.post('/clanmgmt',
                         {'create_clan': '', 'clan_name': 'Testers'})
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.clan.name, 'Testers')
        self.assertFalse(self.alice.looking_for_clan)
        # the message stays, ready if they look again later
        self.assertEqual(self.alice.lfc_message, 'hi')

    def test_joining_a_clan_clears_the_flag(self):
        set_lfc(self.client, message='hi')
        clan = Clan.objects.create(name='Testers')
        self.alice.invites.add(clan)
        self.client.post('/clanmgmt',
                         {'join_clan': '', 'join_clan_id': clan.id})
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.clan, clan)
        self.assertFalse(self.alice.looking_for_clan)


class PublicDisplayTests(LookingForClanTestCase):

    def setUp(self):
        super().setUp()
        # no games: being listed does not need any (unlike /players)
        Player.objects.create(name='alice', looking_for_clan=True,
                              lfc_message='<b>first ascension</b> soon!')
        Player.objects.create(name='bob', looking_for_clan=True)
        Player.objects.create(name='carol', lfc_message='not flagged')
        # flagged, but in a clan (left over, or set in the database)
        Player.objects.create(name='dave', looking_for_clan=True,
                              lfc_message='in a clan',
                              clan=Clan.objects.create(name='Testers'))

    def test_clans_page_lists_flagged_clanless_players(self):
        resp = self.client.get('/clans')
        self.assertEqual([p['name'] for p in resp.context['lfc_players']],
                         ['alice', 'bob'])
        self.assertContains(resp, 'Looking for a Clan')
        # messages are escaped
        self.assertContains(resp, '&lt;b&gt;first ascension&lt;/b&gt; soon!')
        self.assertNotContains(resp, '<b>first ascension</b>')
        self.assertNotContains(resp, 'not flagged')
        self.assertNotContains(resp, 'in a clan')

    def test_profile_page(self):
        resp = self.client.get('/player/alice')
        self.assertTrue(resp.context['looking_for_clan'])
        self.assertContains(resp, 'Looking for a clan')
        self.assertContains(resp, '&lt;b&gt;first ascension&lt;/b&gt; soon!')
        for name in ('carol', 'dave'):
            resp = self.client.get('/player/' + name)
            self.assertFalse(resp.context['looking_for_clan'])
            self.assertNotContains(resp, 'Looking for a clan')
        self.assertFalse(
            self.client.get('/clan/Testers').context.get('looking_for_clan'))

    def test_empty_list(self):
        Player.objects.update(looking_for_clan=False)
        resp = self.client.get('/clans')
        self.assertContains(resp, 'no players are looking for a clan')

    def test_hidden_during_clan_freeze(self):
        self.close_clans()
        resp = self.client.get('/clans')
        self.assertNotIn('lfc_players', resp.context)
        self.assertNotContains(resp, 'Looking for a Clan')
        self.assertNotContains(self.client.get('/player/alice'),
                               'first ascension')

    def test_hidden_after_the_tournament(self):
        # e.g. CLAN_FREEZE_TIME disabled: archived pages still never show it
        now = datetime.now(tz=timezone.utc)
        self.patch_times(freeze=None, end=now - timedelta(minutes=1))
        self.assertNotContains(self.client.get('/clans'),
                               'Looking for a Clan')
        self.assertNotContains(self.client.get('/player/alice'),
                               'first ascension')


class ClanAdminListTests(LookingForClanTestCase):
    fixtures = ['sources']

    def setUp(self):
        super().setUp()
        self.clan = Clan.objects.create(name='Testers')
        self.admin = login_player(self.client, 'zed', self.clan, admin=True)
        self.alice = Player.objects.create(name='alice',
                                           looking_for_clan=True,
                                           lfc_message='pick me')
        self.bob = Player.objects.create(name='bob', looking_for_clan=True)
        self.bob.invites.add(self.clan)
        patcher = mock.patch.object(hardfought_utils, 'DGL_DATABASE_PATH',
                                    'dgamelaunch_test.db')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_admin_sees_list_with_invite_buttons(self):
        resp = self.client.get('/clanmgmt')
        self.assertEqual([p.name for p in resp.context['lfc_players']],
                         ['alice', 'bob'])
        self.assertContains(resp, 'pick me')
        self.assertContains(resp, 'name="invitee" type="hidden" '
                                  'value="alice"')
        # bob already has this clan's invite
        self.assertNotContains(resp, 'value="bob"')
        self.assertContains(resp, '(invited)')

    def test_invite_button_invites(self):
        resp = self.client.post('/clanmgmt',
                                {'invite': '', 'invitee': 'alice'})
        self.assertNotIn('errmsg', resp.context)
        self.assertIn(self.clan, self.alice.invites.all())
        self.assertNotContains(resp, 'value="alice"')

    def test_non_admin_member_does_not_see_the_list(self):
        login_player(self.client, 'mem', self.clan)
        resp = self.client.get('/clanmgmt')
        self.assertNotIn('lfc_players', resp.context)
        self.assertNotContains(resp, 'pick me')


class AdminPanelLfcTests(LookingForClanTestCase):

    def setUp(self):
        super().setUp()
        self.alice = Player.objects.create(name='alice',
                                           looking_for_clan=True,
                                           lfc_message='rude words')
        # a stored message that is not shown right now is listed too
        Player.objects.create(name='bob', lfc_message='later')
        Player.objects.create(name='carol')
        for name in ('get_multi_account_ips', 'get_players_last_ips'):
            patcher = mock.patch.object(hardfought_utils, name,
                                        return_value=[] if 'multi' in name
                                        else {})
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_admin_sees_and_clears_entries(self):
        login_player(self.client, 'k2')  # in SITE_ADMINS
        resp = self.client.get('/admin-panel')
        self.assertEqual([p.name for p in resp.context['lfc_entries']],
                         ['alice', 'bob'])
        self.assertContains(resp, 'rude words')
        resp = self.client.post('/admin-panel', {
            'clear_lfc': '', 'lfc_player_id': self.alice.id})
        self.assertRedirects(resp, '/admin-panel',
                             fetch_redirect_response=False)
        self.alice.refresh_from_db()
        self.assertFalse(self.alice.looking_for_clan)
        self.assertEqual(self.alice.lfc_message, '')

    def test_bad_id_is_ignored(self):
        login_player(self.client, 'k2')
        for bad in ('abc', '999999', None):
            data = {'clear_lfc': ''}
            if bad is not None:
                data['lfc_player_id'] = bad
            resp = self.client.post('/admin-panel', data)
            self.assertEqual(resp.status_code, 302)
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.lfc_message, 'rude words')

    def test_non_admin_cannot_clear(self):
        login_player(self.client, 'mallory')
        resp = self.client.post('/admin-panel', {
            'clear_lfc': '', 'lfc_player_id': self.alice.id})
        self.assertEqual(resp.status_code, 403)
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.lfc_message, 'rude words')
