"""
Put the scoreboard's data into test mode and take it out again. This is
the database half of test_mode.sh in the project root, which also turns
DEBUG on for the site, so that logins are checked against
dgamelaunch_test.db (tnnt/settings.py):

    ./manage.py test_mode on --state FILE [--backup PATH] [--dry-run]
    ./manage.py test_mode off --state FILE [--dry-run]
    ./manage.py test_mode status [--state FILE]

on writes down what the database holds in FILE (the highest User, Player,
Clan and Game ids, and the SiteSettings switches), turns non-admin logins
and clan operations on, and loads the test xlogfiles with load_test_xlogs,
all in one transaction.

off deletes everything created since then and puts the switches back, in
one transaction: the clans, the games from before TOURNAMENT_START, the
players left without games, and the logins (Users) left without players,
with their sessions. Test players can only add rows (log in, found a clan,
invite anyone, which creates a Player), so this undoes whatever they did.
It never deletes a game from the tournament itself or that game's player,
and never a User named in SITE_ADMINS. Then it runs aggregate, and renames
FILE to FILE.reverted-<time>.

--dry-run does the whole job, for on including a login as a test player
against dgamelaunch_test.db, and rolls the transaction back. The donor
files are not fetched and only warnings are logged, so nothing outside the
console changes. DEBUG messages are never logged while this runs.
"""
import json
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Max
from django.test import Client

from scoreboard.models import Clan, Game, Player, SiteSettings
from tnnt import hardfought_utils, settings

logger = logging.getLogger()  # root logger

# the SiteSettings fields that on sets and off puts back
SWITCHES = ('login_enabled', 'clan_operations_enabled')

# the tables whose new rows off deletes, by their key in the state file
MODELS = (('user', User), ('player', Player), ('clan', Clan),
          ('game', Game))

# The login database tnnt/settings.py uses when DEBUG is on (a path
# relative to the project directory, where the site runs), and one of its
# accounts (README.md: every password is the account's name)
TEST_DGL_DATABASE = Path(__file__).resolve().parents[3] / 'dgamelaunch_test.db'
TEST_ACCOUNT = 'alice'


class DryRunDone(Exception):
    """Raised at the end of a dry run to roll its transaction back."""


@contextmanager
def quiet(dry_run):
    """
    Keep pollxlogs' DEBUG line per imported game off the console. For a
    dry run, also keep aggregate from fetching the donor files, and INFO
    messages about work that is about to be rolled back out of the log.
    """
    logging.disable(logging.INFO if dry_run else logging.DEBUG)
    try:
        if dry_run:
            with mock.patch.object(settings, 'DONOR_FILES', []):
                yield
        else:
            yield
    finally:
        logging.disable(logging.NOTSET)


class Command(BaseCommand):
    help = ('Take the database into test mode (test games loaded, logins '
            'and clan operations on) and back out again; see test_mode.sh.')

    def add_arguments(self, parser):
        parser.add_argument('action', choices=('on', 'off', 'status'))
        parser.add_argument(
            '--state', type=Path,
            help='file that on writes and off reads (required for on and '
                 'off)')
        parser.add_argument(
            '--backup',
            help='with on: path of the database backup, kept in the state '
                 'file for reference')
        parser.add_argument(
            '--dry-run', action='store_true',
            help='do everything, then roll back')

    def handle(self, *args, **options):
        action = options['action']
        state_path = options['state']
        if action in ('on', 'off') and state_path is None:
            raise CommandError('%s needs --state' % action)
        if action == 'on':
            self.on(state_path, options['backup'], options['dry_run'])
        elif action == 'off':
            self.off(state_path, options['dry_run'])
        else:
            self.status(state_path)

    def snapshot(self, backup):
        """What the database holds now, as written to the state file."""
        site = SiteSettings.load()
        return {
            'created': datetime.now(timezone.utc).isoformat(),
            'backup': backup,
            'max_ids': {
                key: model.objects.aggregate(top=Max('id'))['top'] or 0
                for key, model in MODELS},
            'site_settings': {
                name: getattr(site, name) for name in SWITCHES + (
                    'updated_by',)},
        }

    def on(self, state_path, backup, dry_run):
        if state_path.exists():
            raise CommandError('%s exists: the database is already in test '
                               'mode' % state_path)
        live_start = settings.TOURNAMENT_START
        if Game.objects.filter(starttime__lt=live_start).exists():
            raise CommandError(
                'the database already holds games from before %s; take them '
                'out first (./manage.py load_test_xlogs --remove)'
                % live_start)

        state = self.snapshot(backup)
        if not dry_run:
            # written before the transaction, so that test mode is never
            # on without it; removed again if the transaction fails
            try:
                state_path.write_text(json.dumps(state, indent=2) + '\n')
            except OSError as e:
                raise CommandError('cannot write %s: %s' % (state_path, e))
        try:
            with quiet(dry_run), transaction.atomic():
                site = SiteSettings.load()
                for name in SWITCHES:
                    setattr(site, name, True)
                site.updated_by = 'test_mode'
                site.save()
                out = StringIO()
                call_command('load_test_xlogs', stdout=out,
                             stderr=self.stderr)
                # its closing advice is for loading without test mode
                self.stdout.write(''.join(
                    line for line in out.getvalue().splitlines(True)
                    if not line.startswith('Aggregated.')), ending='')
                if dry_run:
                    self.try_test_login()
                    raise DryRunDone
        except DryRunDone:
            self.stdout.write('Dry run: test mode would go on as above; '
                              'rolled back.')
            return
        except BaseException:
            if not dry_run:
                state_path.unlink(missing_ok=True)
            raise
        logger.info('Test mode on; state in %s', state_path)
        self.stdout.write('Test mode on. Logins and clan operations '
                          'enabled; state written to %s.' % state_path)

    def try_test_login(self):
        """
        Log in as a test player the way the site will in DEBUG mode, and
        check that the login took. Raises CommandError if it did not.
        """
        if not TEST_DGL_DATABASE.is_file():
            raise CommandError('no %s' % TEST_DGL_DATABASE)
        client = Client(HTTP_HOST='tnnt.org')
        with mock.patch.object(hardfought_utils, 'DGL_DATABASE_PATH',
                               str(TEST_DGL_DATABASE)):
            response = client.post('/login/', {
                'username': TEST_ACCOUNT, 'password': TEST_ACCOUNT})
        if response.status_code != 302 or '_auth_user_id' not in \
                client.session:
            raise CommandError(
                'logging in as %s failed (HTTP %d, redirect to %s)'
                % (TEST_ACCOUNT, response.status_code,
                   response.get('Location')))
        response = client.get('/player/%s' % TEST_ACCOUNT)
        if response.status_code != 200:
            raise CommandError('/player/%s after logging in: HTTP %d'
                               % (TEST_ACCOUNT, response.status_code))
        self.stdout.write('Logged in as %s against %s, then /player/%s: '
                          '200.' % (TEST_ACCOUNT, TEST_DGL_DATABASE.name,
                                    TEST_ACCOUNT))

    def read_state(self, state_path):
        try:
            state = json.loads(state_path.read_text())
            max_ids = {key: int(state['max_ids'][key]) for key, _ in MODELS}
            switches = {name: bool(state['site_settings'][name])
                        for name in SWITCHES}
            updated_by = state['site_settings'].get('updated_by')
        except FileNotFoundError:
            raise CommandError('%s does not exist: the database is not in '
                               'test mode' % state_path)
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise CommandError('cannot read %s: %s' % (state_path, e))
        return max_ids, switches, updated_by

    def off(self, state_path, dry_run):
        max_ids, switches, updated_by = self.read_state(state_path)
        live_start = settings.TOURNAMENT_START
        try:
            with quiet(dry_run), transaction.atomic():
                counts = self.delete_test_rows(max_ids, live_start)
                site = SiteSettings.load()
                for name, value in switches.items():
                    setattr(site, name, value)
                site.updated_by = updated_by
                site.save()
                call_command('aggregate')
                verb = 'Would delete' if dry_run else 'Deleted'
                self.stdout.write(
                    '%s %d clans, %d games from before %s, %d players, %d '
                    'logins and %d sessions; switches back to %s.'
                    % (verb, counts['clans'], counts['games'], live_start,
                       counts['players'], counts['users'],
                       counts['sessions'], ', '.join(
                           '%s=%s' % item for item in switches.items())))
                if counts['kept_players'] or counts['kept_users']:
                    self.stdout.write(
                        'Kept %d players with tournament games and %d logins '
                        'still in use, though created after test mode went '
                        'on.' % (counts['kept_players'],
                                 counts['kept_users']))
                if dry_run:
                    raise DryRunDone
        except DryRunDone:
            self.stdout.write('Dry run: rolled back.')
            return
        logger.info('Test mode off: deleted %d clans, %d games, %d players, '
                    '%d logins', counts['clans'], counts['games'],
                    counts['players'], counts['users'])
        done = state_path.with_name('%s.reverted-%s' % (
            state_path.name, datetime.now().strftime('%Y%m%d_%H%M%S')))
        try:
            state_path.rename(done)
        except OSError as e:
            raise CommandError('test mode is off, but %s could not be '
                               'renamed: %s; delete it by hand'
                               % (state_path, e))
        self.stdout.write('Test mode off; state file moved to %s.' % done)

    def delete_test_rows(self, max_ids, live_start):
        """
        Delete the rows created after the state was written; return how
        many of each were deleted, and how many were kept.
        """
        counts = {}
        clans = Clan.objects.filter(id__gt=max_ids['clan'])
        counts['clans'] = clans.count()
        clans.delete()

        games = Game.objects.filter(id__gt=max_ids['game'],
                                    starttime__lt=live_start)
        counts['games'] = games.count()
        games.delete()

        new_players = Player.objects.filter(id__gt=max_ids['player'])
        players = new_players.filter(game__isnull=True)
        counts['players'] = players.count()
        counts['kept_players'] = new_players.count() - counts['players']
        players.delete()

        new_users = User.objects.filter(id__gt=max_ids['user']).exclude(
            username__in=settings.SITE_ADMINS)
        users = new_users.filter(player__isnull=True)
        user_ids = {str(pk) for pk in users.values_list('id', flat=True)}
        counts['users'] = len(user_ids)
        counts['kept_users'] = new_users.count() - counts['users']
        sessions = [session.pk for session in Session.objects.all()
                    if session.get_decoded().get('_auth_user_id') in user_ids]
        counts['sessions'] = len(sessions)
        Session.objects.filter(pk__in=sessions).delete()
        users.delete()
        return counts

    def status(self, state_path):
        site = SiteSettings.load()
        self.stdout.write('Switches: %s (last set by %s)' % (
            ', '.join('%s=%s' % (name, getattr(site, name))
                      for name in SWITCHES), site.updated_by))
        self.stdout.write('Rows: %s; games from before %s: %d' % (
            ', '.join('%s %d' % (key, model.objects.count())
                      for key, model in MODELS),
            settings.TOURNAMENT_START, Game.objects.filter(
                starttime__lt=settings.TOURNAMENT_START).count()))
        if state_path is None:
            return
        if state_path.exists():
            self.stdout.write('In test mode since %s (state file %s)' % (
                json.loads(state_path.read_text()).get('created'),
                state_path))
        else:
            self.stdout.write('Not in test mode (no %s)' % state_path)
