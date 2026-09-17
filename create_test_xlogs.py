#!/usr/bin/env python3
"""
create_test_xlogs.py - Build the test xlogfiles from a tournament archive

Usage: ./create_test_xlogs.py <year> [--seed N] [--out-dir DIR]

Reads the archived per-server xlogfiles in
tnnt/static/archives/<year>/xlogfiles/ and writes test-us.xlog,
test-eu.xlog and test-au.xlog: 1000 real games each, renamed to the nine
accounts in dgamelaunch_test.db (three per server). Each file holds 60
ascensions, 90 scummed games, 650 other games with TNNT achievements and
200 games without, and no game appears in more than one file.

Only the name= and server= fields of a record are changed; everything
else, field order included, is copied as it is. Games are drawn from all
three servers and filtered the way pollxlogs filters them (required
fields present, no wizard or explore mode, inside November of <year>).
No two selected games share a starttime: the games are handed to other
players, and Player.get_streaks() assumes that a player never has two
games that started in the same second.

The output is the same for a given year and seed. Run it with the
virtualenv active. It uses the SQLite test settings, so it needs neither
secrets.sh nor the database. Load the files into the scoreboard with
`./manage.py load_test_xlogs`.
"""

import argparse
import os
import random
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

SERVERS = ('us', 'eu', 'au')

# The dgamelaunch_test.db accounts that play on each server
USERS = {
    'us': ('alice', 'bob', 'chuck'),
    'eu': ('david', 'eve', 'gimli'),
    'au': ('janet', 'omghax', 'sally'),
}

# Games per file from each category. Categories are checked in this order
# and a game belongs to the first one that matches.
TARGETS = (
    ('ascended', 60),
    ('scummed', 90),
    ('achievements', 650),
    ('normal', 200),
)
GAMES_PER_FILE = sum(count for _, count in TARGETS)

# pollxlogs counts a game as won when this achieve bit is set
ACHIEVE_ASCENDED = 0x100


def setup_django():
    """Configure Django with the SQLite test settings."""
    sys.path.insert(0, str(BASE_DIR))
    # Forced rather than defaulted: the production settings would connect
    # to MariaDB and open the production log file.
    os.environ['DJANGO_SETTINGS_MODULE'] = 'tnnt.settings_test'
    try:
        import django
    except ImportError:
        sys.exit('Cannot import Django; activate the virtualenv first '
                 '(source env/bin/activate)')
    django.setup()


def get_archive_dir(year):
    """Get the xlogfile directory of a year's tournament archive."""
    return BASE_DIR / 'tnnt' / 'static' / 'archives' / str(year) / 'xlogfiles'


def read_games(year):
    """
    Return every game in the year's per-server xlogfiles that pollxlogs
    would import, as (entry, fields) tuples: entry is the parsed record
    and fields is the original line split on tabs.
    """
    from scoreboard.management.commands.pollxlogs import (
        REQUIRED_XLOG_FIELDS, xlog_flags)
    from scoreboard.parsers import parse_xlog_line

    start = int(datetime(year, 11, 1, tzinfo=timezone.utc).timestamp())
    end = int(datetime(year, 12, 1, tzinfo=timezone.utc).timestamp())
    unwanted_flags = xlog_flags.WIZARD | xlog_flags.EXPLORE
    games = []
    for server in SERVERS:
        path = get_archive_dir(year) / ('xlogfile-%s' % server)
        try:
            with path.open('rb') as xlog_file:
                data = xlog_file.read()
        except OSError as e:
            sys.exit('Cannot read %s: %s' % (path, e))

        kept = excluded = 0
        for raw_line in data.split(b'\n'):
            if not raw_line.strip():
                continue
            try:
                line = raw_line.decode('utf-8')
                entry = parse_xlog_line(line)
            except ValueError:
                # UnicodeDecodeError is a ValueError too
                excluded += 1
                continue
            if (REQUIRED_XLOG_FIELDS.difference(entry)
                    or entry['flags'] & unwanted_flags
                    or entry['starttime'] < start
                    or entry['endtime'] > end):
                excluded += 1
                continue
            games.append((entry, line.split('\t')))
            kept += 1
        print('%s: %d games, %d lines excluded' % (path, kept, excluded))
    return games


def has_achievements(entry):
    """True if any of the game's tnntachieve bitfields is set."""
    return any(value for key, value in entry.items()
               if key.startswith('tnntachieve'))


def category(entry):
    """The TARGETS category a parsed game belongs to."""
    from scoreboard.models import is_scummed

    if entry['achieve'] & ACHIEVE_ASCENDED:
        return 'ascended'
    if is_scummed(entry):
        return 'scummed'
    if has_achievements(entry):
        return 'achievements'
    return 'normal'


def build_pools(games, rng):
    """
    Sort the games into shuffled per-category pools, keeping only the
    first game (in time order) of each starttime. Return the pools and
    the number of games dropped for sharing a starttime.
    """
    pools = {name: [] for name, _ in TARGETS}
    starttimes = set()
    dropped = 0
    for game in sorted(games, key=lambda g: (g[0]['starttime'],
                                             g[0]['endtime'])):
        entry = game[0]
        if entry['starttime'] in starttimes:
            dropped += 1
            continue
        starttimes.add(entry['starttime'])
        pools[category(entry)].append(game)
    for pool in pools.values():
        rng.shuffle(pool)
    return pools, dropped


def rename(fields, name, server):
    """Return the record as a line, with its name and server replaced."""
    fields = list(fields)
    for key, value in (('name', name),
                       ('server', '%s.hardfought.org' % server)):
        where = [i for i, field in enumerate(fields)
                 if field.partition('=')[0] == key]
        if len(where) != 1:
            sys.exit('A record has %d %s= fields: %s'
                     % (len(where), key, '\t'.join(fields)[:200]))
        fields[where[0]] = '%s=%s' % (key, value)
    return '\t'.join(fields)


def player_sizes(count, players):
    """Split `count` games as evenly as possible, extras to the first."""
    return [count // players + (1 if i < count % players else 0)
            for i in range(players)]


def write_test_file(path, server, picks, rng):
    """Hand the picked games to the server's test players and write them."""
    from scoreboard.models import is_scummed

    rng.shuffle(picks)
    records = []
    per_player = Counter()
    offset = 0
    for name, size in zip(USERS[server],
                          player_sizes(len(picks), len(USERS[server]))):
        for entry, fields in picks[offset:offset + size]:
            records.append((entry, rename(fields, name, server)))
            per_player[name] += 1
        offset += size
    # a real xlogfile is in the order games end
    records.sort(key=lambda r: (r[0]['endtime'], r[0]['starttime']))

    try:
        with path.open('w', encoding='utf-8', newline='\n') as out:
            out.writelines(line + '\n' for _, line in records)
    except OSError as e:
        sys.exit('Cannot write %s: %s' % (path, e))

    categories = Counter(category(entry) for entry, _ in records)
    print('%s: %d games' % (path, len(records)))
    print('  by category: %s' % ', '.join(
        '%s %d' % (name, categories[name]) for name, _ in TARGETS))
    print('  with any achievement bits: %d, scummed: %d' % (
        sum(1 for entry, _ in records if has_achievements(entry)),
        sum(1 for entry, _ in records if is_scummed(entry))))
    print('  per player: %s' % ', '.join(
        '%s %d' % item for item in per_player.items()))


def main():
    parser = argparse.ArgumentParser(
        description='Build test-{us,eu,au}.xlog from a tournament archive.')
    parser.add_argument('year', type=int,
                        help='tournament year whose archive to read')
    parser.add_argument('--seed', type=int, default=42,
                        help='random seed (default: %(default)s)')
    parser.add_argument('--out-dir', type=Path, default=BASE_DIR,
                        help='where to write the files '
                             '(default: the project directory)')
    args = parser.parse_args()

    if not args.out_dir.is_dir():
        sys.exit('Output directory %s does not exist' % args.out_dir)

    setup_django()
    rng = random.Random(args.seed)
    pools, dropped = build_pools(read_games(args.year), rng)
    print('Pools: %s; %d games dropped for a shared starttime' % (
        ', '.join('%s %d' % (name, len(pools[name])) for name, _ in TARGETS),
        dropped))

    for name, count in TARGETS:
        needed = count * len(SERVERS)
        if len(pools[name]) < needed:
            sys.exit('The %d archive has only %d %s games; %d are needed'
                     % (args.year, len(pools[name]), name, needed))

    for i, server in enumerate(SERVERS):
        # each file takes the next slice of every pool, so no game is
        # used twice
        picks = []
        for name, count in TARGETS:
            picks.extend(pools[name][i * count:(i + 1) * count])
        write_test_file(args.out_dir / ('test-%s.xlog' % server), server,
                        picks, rng)


if __name__ == '__main__':
    main()
