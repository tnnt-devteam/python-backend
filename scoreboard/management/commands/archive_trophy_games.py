"""
Write the trophy grid's per-cell game lists for a tournament archive.

The archived player and clan pages keep their Trophy Progress Tracker,
but the live API behind its clickable cells (/api/trophy-grid-games/)
looks players and clans up by database id. Ids are reissued every
tournament and the database is wiped in between, so an archived page
must not call the live API at all. Instead each archive carries one
static JSON file per player and per clan with the games of every
role-race-alignment combo, cleanup_archive.py points each page's grid at
its file (a `data-archive-games` attribute on the grid container) and
trophy-grid.js reads that file instead of the API.

Run it after archive_tournament.sh and BEFORE the database is wiped:

    ./manage.py archive_trophy_games 2026

Output: tnnt/static/archives/<year>/api/trophy-grid-games/<type>/<name>.json
where <type> is `player` or `clan` and <name> is the entity's exact name.

Each file looks like:

    {"entity_type": "player", "name": "spazm", "combos": {
        "Val-Hum-Law": {"mines_soko": [...], "male_ascensions": [...],
                        "female_ascensions": [...]}, ...}}

with one entry per game (player__name, endtime, points, turns, dumplog),
the same field names the live API answers with, newest game first. Only
combos with at least one game are listed.
"""
import json
import logging
import os
import re

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from scoreboard.models import Clan, Game, Player
from tnnt import dumplog_utils

logger = logging.getLogger()  # root logger

SECTIONS = ('mines_soko', 'male_ascensions', 'female_ascensions')


def game_entry(row):
    """
    The fields trophy-grid.js shows for one game, named and formatted as
    the live API (TrophyGridGamesView via bulk_upd_games) names them.
    `row` is a Game.objects.values() dict from collect_games().
    """
    return {
        'player__name': row['player__name'],
        'endtime': row['endtime'].strftime('%Y-%m-%d %H:%M'),
        'points': row['points'],
        'turns': row['turns'],
        'dumplog': dumplog_utils.format_dumplog(
            row['source__dumplog_fmt'], row['player__name'],
            row['starttime']),
    }


def collect_games():
    """
    Return (player_combos, clan_combos): dicts keyed by Player id and Clan
    id whose values are {'Rol-Rac-Aln': {section: [entries]}} for every
    ascended or Mines+Soko game, built from a single query. A clan's lists
    hold its current members' games, as the live grid and API do. Lists
    are newest first, matching the API's ordering.
    """
    players = {}
    clans = {}
    rows = Game.objects.filter(Q(won=True) | Q(mines_soko=True)).values(
        'player_id', 'player__name', 'player__clan_id', 'role', 'race',
        'align0', 'gender0', 'won', 'mines_soko', 'starttime', 'endtime',
        'points', 'turns', 'source__dumplog_fmt').order_by('-endtime')
    for row in rows:
        sections = []
        if row['mines_soko']:
            sections.append('mines_soko')
        if row['won']:
            if row['gender0'] == 'Mal':
                sections.append('male_ascensions')
            elif row['gender0'] == 'Fem':
                sections.append('female_ascensions')
        if not sections:
            continue
        entry = game_entry(row)
        key = '%s-%s-%s' % (row['role'], row['race'], row['align0'])
        targets = [players.setdefault(row['player_id'], {})]
        if row['player__clan_id'] is not None:
            targets.append(clans.setdefault(row['player__clan_id'], {}))
        for combos in targets:
            combo = combos.setdefault(key, {s: [] for s in SECTIONS})
            for section in sections:
                combo[section].append(entry)
    return players, clans


def write_entity_file(directory, entity_type, name, combos):
    """
    Write <directory>/<name>.json. Return False (after a warning) for a
    name that cannot be a file name; the form layer refuses slashes in
    clan names, so this only guards against rows that bypassed it.
    """
    if os.sep in name or name in ('', '.', '..'):
        logger.warning('archive_trophy_games: skipping %s %r, the name '
                       'cannot be a file name', entity_type, name)
        return False
    path = os.path.join(directory, name + '.json')
    data = {'entity_type': entity_type, 'name': name, 'combos': combos}
    with open(path, 'w', encoding='utf-8') as outfile:
        json.dump(data, outfile, indent=1)
    return True


class Command(BaseCommand):
    help = ('Write static trophy-grid game lists (one JSON file per player '
            'and clan) into a tournament archive. Run after '
            'archive_tournament.sh and before the database is wiped.')

    def add_arguments(self, parser):
        parser.add_argument(
            'year',
            help='tournament year; files go under tnnt/static/archives/'
                 '<year>/api/trophy-grid-games/')
        parser.add_argument(
            '--archive-dir',
            help='write under this archive directory instead of the one '
                 'derived from the year (it must already exist)')

    def handle(self, *args, **options):
        year = options['year']
        if not re.fullmatch(r'\d{4}', year):
            raise CommandError('year must be four digits, not %r' % year)
        archive_dir = options['archive_dir'] or os.path.join(
            settings.BASE_DIR, 'tnnt', 'static', 'archives', year)
        if not os.path.isdir(archive_dir):
            raise CommandError(
                '%s does not exist; run archive_tournament.sh %s first'
                % (archive_dir, year))

        player_combos, clan_combos = collect_games()
        base = os.path.join(archive_dir, 'api', 'trophy-grid-games')
        written = {}
        for entity_type, model, combos in (
                ('player', Player, player_combos),
                ('clan', Clan, clan_combos)):
            directory = os.path.join(base, entity_type)
            try:
                os.makedirs(directory, exist_ok=True)
            except OSError as err:
                raise CommandError('cannot create %s: %s' % (directory, err))
            written[entity_type] = 0
            for entity in model.objects.order_by('name'):
                if write_entity_file(directory, entity_type, entity.name,
                                     combos.get(entity.id, {})):
                    written[entity_type] += 1
        self.stdout.write('Wrote %d player and %d clan game files under %s'
                          % (written['player'], written['clan'], base))
