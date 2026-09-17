"""
Load the tracked test xlogfiles into the scoreboard, or take them out.

test-us.xlog, test-eu.xlog and test-au.xlog (built by create_test_xlogs.py
in the project root) hold real games from the previous tournament,
renamed to the nine dgamelaunch_test.db accounts. pollxlogs only imports
games inside settings.TOURNAMENT_START..TOURNAMENT_END, which already
names the next tournament during the off-season, so `pollxlogs --file`
filters every one of them out. This command imports them with the window
moved to November of the files' year, for the import only, and then runs
aggregate:

    ./manage.py load_test_xlogs                     # the three test files
    ./manage.py load_test_xlogs FILE ... --year 2025

and takes them out again:

    ./manage.py load_test_xlogs --remove --dry-run
    ./manage.py load_test_xlogs --remove [FILE ...]

Removal deletes the games that started before settings.TOURNAMENT_START
and belong to the players named in the files, so a real player who
shares a test name keeps their tournament games. It then deletes those
players unless something else refers to them (a tournament game, a
login, a clan, an invite or a temporary achievement), and runs aggregate.

Test games left in the database count towards the standings (aggregate
does not look at game dates), so remove them before TOURNAMENT_START,
then restart tnntbot: the bot remembers which players disappeared and
would not announce the first trophies of a real player with one of the
test names.

Loading is refused while the tournament is on, and while its games are
still in the database.
"""
import logging
from datetime import datetime, timezone
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from scoreboard.management.commands.pollxlogs import (
    ADDED, BAD, DUPLICATE, FILTERED, import_from_file,
)
from scoreboard.models import Game, Player, Source
from scoreboard.parsers import parse_xlog_line
from tnnt import settings

logger = logging.getLogger()  # root logger

TEST_FILES = ('test-us.xlog', 'test-eu.xlog', 'test-au.xlog')


def import_window(year):
    """The tournament window of `year`: November, in UTC."""
    return (datetime(year, 11, 1, tzinfo=timezone.utc),
            datetime(year, 12, 1, tzinfo=timezone.utc))


def player_names(paths):
    """The player names found in the given xlogfiles."""
    names = set()
    for path in paths:
        try:
            with open(path, 'rb') as xlog_file:
                for raw_line in xlog_file:
                    line = raw_line.decode('utf-8', errors='replace')
                    if not line.strip():
                        continue
                    try:
                        name = parse_xlog_line(line).get('name')
                    except ValueError:
                        continue
                    if name:
                        names.add(name)
        except OSError as err:
            raise CommandError('cannot read %s: %s' % (path, err))
    return names


class Command(BaseCommand):
    help = ('Load the test xlogfiles (games from an earlier tournament) '
            'into the scoreboard, or remove them with --remove.')

    def add_arguments(self, parser):
        parser.add_argument(
            'files', nargs='*',
            help='xlogfiles to load or remove (default: %s in the project '
                 'directory)' % ', '.join(TEST_FILES))
        parser.add_argument(
            '--year', type=int,
            help='year the games were played in (default: the year before '
                 'settings.TOURNAMENT_START)')
        parser.add_argument(
            '--remove', action='store_true',
            help="delete the files' players' games from before "
                 'settings.TOURNAMENT_START, and those players if nothing '
                 'else refers to them')
        parser.add_argument(
            '--dry-run', action='store_true',
            help='with --remove: only report what would be deleted')

    def handle(self, *args, **options):
        paths = [Path(f) for f in options['files']] or [
            Path(settings.BASE_DIR) / name for name in TEST_FILES]
        missing = [str(p) for p in paths if not p.is_file()]
        if missing:
            raise CommandError('no such file: %s' % ', '.join(missing))

        if options['remove']:
            if options['year'] is not None:
                raise CommandError('--year only applies when loading')
            self.remove(paths, options['dry_run'])
        else:
            if options['dry_run']:
                raise CommandError('--dry-run only applies to --remove')
            year = options['year']
            if year is None:
                year = settings.TOURNAMENT_START.year - 1
            self.load(paths, year)

    def load(self, paths, year):
        live_start = settings.TOURNAMENT_START
        live_end = settings.TOURNAMENT_END
        start, end = import_window(year)
        if live_start <= datetime.now(timezone.utc) <= live_end:
            raise CommandError('the tournament is on (%s to %s); not '
                               'loading test games' % (live_start, live_end))
        if Game.objects.filter(starttime__gte=live_start).exists():
            raise CommandError('the database holds games from the %s '
                               'tournament; not loading test games'
                               % live_start.year)
        if end > live_start:
            # --remove could not tell such games from tournament games
            raise CommandError('games from %d do not end before the '
                               'tournament starts (%s)' % (year, live_start))
        if not Source.objects.exists():
            raise CommandError('there are no sources in the database; run '
                               'loaddata sources first')

        # pollxlogs reads the window from the tnnt.settings module when it
        # filters each game, so move it for the import and always put it
        # back.
        settings.TOURNAMENT_START, settings.TOURNAMENT_END = start, end
        try:
            for path in paths:
                counts = import_from_file(path, None)
                self.stdout.write(
                    '%s: %d added, %d filtered, %d duplicates, %d bad'
                    % (path, counts[ADDED], counts[FILTERED],
                       counts[DUPLICATE], counts[BAD]))
        finally:
            settings.TOURNAMENT_START = live_start
            settings.TOURNAMENT_END = live_end
        logger.info('Loaded test games from %s', ', '.join(map(str, paths)))
        call_command('aggregate')
        self.stdout.write('Aggregated. Remove the test games before %s with '
                          '`./manage.py load_test_xlogs --remove`.'
                          % live_start)

    def remove(self, paths, dry_run):
        live_start = settings.TOURNAMENT_START
        names = player_names(paths)
        games = Game.objects.filter(player__name__in=names,
                                    starttime__lt=live_start)
        # players who will have no games left and nothing else tying them
        # to the site
        players = Player.objects.filter(
            name__in=names, user__isnull=True, clan__isnull=True,
            invites__isnull=True, temp_achievements__isnull=True,
        ).exclude(game__starttime__gte=live_start)

        with transaction.atomic():
            player_ids = sorted(set(players.values_list('id', flat=True)))
            game_count = games.count()
            if not dry_run:
                games.delete()
                Player.objects.filter(id__in=player_ids).delete()

        verb = 'Would delete' if dry_run else 'Deleted'
        self.stdout.write('%s %d games from before %s and %d players '
                          '(names: %s)'
                          % (verb, game_count, live_start, len(player_ids),
                             ', '.join(sorted(names))))
        if dry_run:
            return
        logger.info('Removed %d test games and %d players',
                    game_count, len(player_ids))
        call_command('aggregate')
        self.stdout.write('Aggregated. Restart tnntbot '
                          '(systemctl restart tnntbot) so that it announces '
                          'these names normally again.')
