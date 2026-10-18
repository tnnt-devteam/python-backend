#!/usr/bin/env python3
"""
create_test_xlogs.py - Build the test xlogfiles from a tournament archive

Usage: ./create_test_xlogs.py <year> [--seed N] [--out-dir DIR]

Reads the archived per-server xlogfiles in
tnnt/static/archives/<year>/xlogfiles/ and writes test-us.xlog,
test-eu.xlog and test-au.xlog: 3000 real games each, renamed to the nine
accounts in dgamelaunch_test.db (three per server). Each file holds 100
ascensions, 300 scummed games, 1950 other games with TNNT achievements
and 650 games without, and no game appears in more than one file.

The name= and server= fields of a record are changed. A record written
by an older game (a year in OLD_FORMATS) is also converted to the record
format of the current game, so that it decodes to the same achievements
and conducts under today's fixtures; see RecordConverter. Everything
else, field order included, is copied as it is. Games are drawn from all
three servers and filtered the way pollxlogs filters them (required
fields present, no wizard or explore mode, inside November of <year>).
No two selected games share a starttime: the games are handed to other
players, and Player.get_streaks() assumes that a player never has two
games that started in the same second.

The output is the same for a given year, seed and set of fixtures. The
game moves achievement and conduct bits whenever its lists change, so
rerun this after every resync of the fixtures with the game. Run it with
the virtualenv active. It uses the SQLite test settings, so it needs
neither secrets.sh nor the database, but converting an older year reads
that year's fixtures from the git history of this repository. Load the
files into the scoreboard with `./manage.py load_test_xlogs`.
"""

import argparse
import os
import random
import re
import subprocess
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
# and a game belongs to the first one that matches. Ascensions are the
# scarce category: 2025 has only 326 of them in total, so 100 per file is
# near the ceiling while the rest of the mix is three times the original
# 1000-game split.
TARGETS = (
    ('ascended', 100),
    ('scummed', 300),
    ('achievements', 1950),
    ('normal', 650),
)
GAMES_PER_FILE = sum(count for _, count in TARGETS)

# pollxlogs counts a game as won when this achieve bit is set
ACHIEVE_ASCENDED = 0x100

# The current game, whose record format the files are written in: the
# version it writes, and its top-level dungeons in the order of its
# dat/dungeon.lua, which is the order deathdnum counts in (from 0).
# Re-check both on every resync with the game, like TUTORIAL_DNUM in
# pollxlogs.py.
GAME_VERSION = '5.0.0'
GAME_DUNGEONS = (
    'The Dungeons of Doom', 'Gehennom', 'The Gnomish Mines', 'The Quest',
    'Sokoban', 'Fort Ludios', "Vlad's Tower", 'The Elemental Planes',
    'The Tutorial', 'DevTeam Office', 'Deathmatch Arena',
    'robotfindskitten',
)

# Archive years whose records were written by an older game, and what it
# takes to convert them:
#   fixtures      the commit of this repository whose achievements.yaml
#                 and conducts.yaml decoded that tournament
#   dungeons      that game's top-level dungeons, in deathdnum order
#   achieve_bits  how many low bits of its achieve field mean the same in
#                 the current game; the bits above them are cleared
# A year that is not listed is copied as it is. Add it here once the
# game's achievements or conducts have moved since its tournament.
OLD_FORMATS = {
    # NetHack 3.6.7 based. Its achieve bit 14 was "completed the
    # Deathmatch", which the TNNT achievement Thunderdome also records; in
    # 5.0 that bit means "entered the Gnomish Mines".
    2025: {
        # the last change to the fixtures before the 2025 tournament
        'fixtures': '8b417ad',
        'dungeons': (
            'The Dungeons of Doom', 'Gehennom', 'The Gnomish Mines',
            'The Quest', 'Sokoban', 'Fort Ludios', 'DevTeam Office',
            'Deathmatch Arena', 'robotfindskitten', "Vlad's Tower",
            'The Elemental Planes',
        ),
        'achieve_bits': 14,
    },
}

# Achievements the current game no longer has, mapped to a current one
# that earning them proves: old define -> current define. Only certain
# successors belong here, never a likely one.
ACHIEVEMENT_SUCCESSORS = {
    # the same achievement under a new define
    'A_DID_PURE_SOKOBAN': 'A_COMPLETED_PURE_SOKOBAN',
    # "Step onto the Minetown altar" became "Enter Minetown" under the same
    # name, Back To Civilisation
    'A_FOUND_MINES_ALTAR': 'A_ENTERED_MINETOWN',
}

FIXTURE_FILES = {
    'achievements': 'scoreboard/fixtures/achievements.yaml',
    'conducts': 'scoreboard/fixtures/conducts.yaml',
}

TNNTACHIEVE_FIELD = re.compile(r'tnntachieve(\d+)')


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
        REQUIRED_XLOG_FIELDS, ended_in_tutorial, xlog_flags)
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
                    or ended_in_tutorial(entry)
                    or entry['starttime'] < start
                    or entry['endtime'] > end):
                excluded += 1
                continue
            games.append((entry, line.split('\t')))
            kept += 1
        print('%s: %d games, %d lines excluded' % (path, kept, excluded))
    return games


def read_fixture(name, revision=None):
    """
    Return the records of a fixture as a list of field dicts: the current
    file, or the file as it was in a commit of this repository.
    """
    import yaml

    path = FIXTURE_FILES[name]
    if revision is None:
        try:
            with (BASE_DIR / path).open(encoding='utf-8') as fixture:
                text = fixture.read()
        except OSError as e:
            sys.exit('Cannot read %s: %s' % (path, e))
    else:
        try:
            text = subprocess.run(
                ['git', '-C', str(BASE_DIR), 'show',
                 '%s:%s' % (revision, path)],
                capture_output=True, text=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError) as e:
            sys.exit('Cannot read %s as of commit %s: %s'
                     % (path, revision, getattr(e, 'stderr', '') or e))
    return [record['fields'] for record in yaml.safe_load(text)]


def bit_positions(revision=None):
    """
    Return (achievements, conducts) for the fixtures of a commit, or the
    current ones: achievements maps the define of each achievement to its
    (xlogfield, bit), conducts the shortname of each conduct.
    """
    achievements = {a['define']: (a['xlogfield'], a['bit'])
                    for a in read_fixture('achievements', revision)}
    conducts = {c['shortname']: (c['xlogfield'], c['bit'])
                for c in read_fixture('conducts', revision)}
    return achievements, conducts


class RecordConverter:
    """
    Converts records written by an older game to the record format of the
    current game. A converted record says what the old one said and no
    more:

    - version is the current game's, and deathdnum is the number of the
      same dungeon in the current game
    - each TNNT achievement moves to the bit of the achievement with the
      same define (or its ACHIEVEMENT_SUCCESSORS successor) in the
      current fixtures; any other achievement the current game no longer
      has is dropped
    - each conduct moves to the bit of the conduct with the same
      shortname, in conduct or tnntconduct. A conduct that the old game
      did not track is recorded as broken, as is the vanilla "obeyed
      Sokoban rules" bit, which the scoreboard does not track
    - achieve keeps only the bits that mean the same in both games

    tnntconduct is added after achieve, and the record ends with as many
    tnntachieve fields as the current game writes. The fields that only
    the current game writes and that the old record has nothing for
    (achieveX, conductX, gold, wish_cnt, arti_wish_cnt, bones, rerolls)
    are left out; the scoreboard does not read them.
    """

    def __init__(self, old_format, old_positions, new_positions):
        old_achievements, old_conducts = old_positions
        new_achievements, new_conducts = new_positions

        # (old field, old bit) -> (new field, new bit)
        self.achievements = {}
        self.dropped = {}
        for define, position in old_achievements.items():
            current = define
            if define not in new_achievements:
                current = ACHIEVEMENT_SUCCESSORS.get(define)
            if current in new_achievements:
                self.achievements[position] = new_achievements[current]
            else:
                self.dropped[position] = define
        self.successors = sorted(
            '%s -> %s' % (define, ACHIEVEMENT_SUCCESSORS[define])
            for define in old_achievements
            if define not in new_achievements
            and ACHIEVEMENT_SUCCESSORS.get(define) in new_achievements)

        self.achieve_bits = old_format['achieve_bits']
        self.conducts = {}
        for shortname, position in old_conducts.items():
            if shortname not in new_conducts:
                sys.exit('The current game has no conduct "%s"; decide '
                         'what becomes of it before converting'
                         % shortname)
            new = new_conducts[shortname]
            # conducts kept in achieve (Zen, Nudist) are copied with the
            # achieve bits, so they must not move
            if 'achieve' in (position[0], new[0]) and (
                    position != new or position[1] >= self.achieve_bits):
                sys.exit('Conduct "%s" moves from %s bit %d to %s bit %d; '
                         'RecordConverter cannot move a bit within achieve'
                         % ((shortname,) + position + new))
            self.conducts[position] = new
        self.untracked = sorted(set(new_conducts) - set(old_conducts))
        fields = {field for field, _ in new_conducts.values()}
        if not fields <= {'achieve', 'conduct', 'tnntconduct'}:
            sys.exit('The current conducts use the unknown field(s) %s'
                     % ', '.join(sorted(fields - {'achieve', 'conduct',
                                                  'tnntconduct'})))

        # bits each old field may have set, to catch a wrong fixtures commit
        self.known_bits = Counter()
        for field, bit in list(old_achievements.values()) + [
                position for position in old_conducts
                .values() if position[0] != 'achieve']:
            self.known_bits[field] |= 1 << bit

        try:
            self.dungeons = [GAME_DUNGEONS.index(name)
                             for name in old_format['dungeons']]
        except ValueError as e:
            sys.exit('A dungeon of the old game is not in GAME_DUNGEONS: %s'
                     % e)

        # the game writes NUM_TNNT_ACHIEVEMENTS / 64 + 1 tnntachieve fields
        self.tnntachieve_fields = len(new_achievements) // 64 + 1
        for field, _ in new_achievements.values():
            if int(TNNTACHIEVE_FIELD.fullmatch(field).group(1)) >= \
                    self.tnntachieve_fields:
                sys.exit('Achievement field %s is beyond the %d the game '
                         'writes' % (field, self.tnntachieve_fields))

        self.dropped_seen = Counter()

    def describe(self):
        """A summary of the conversion, for the console."""
        return '\n'.join([
            'Converting to the %s record format: %d achievements kept, %d '
            'of them as a successor (%s); %d dropped (%s)' % (
                GAME_VERSION, len(self.achievements), len(self.successors),
                ', '.join(self.successors) or '-', len(self.dropped),
                ', '.join(sorted(self.dropped.values())) or '-'),
            '  %d conducts kept; %d not tracked by the old game, recorded '
            'as broken: %s' % (len(self.conducts), len(self.untracked),
                               ', '.join(self.untracked) or '-'),
        ])

    def convert(self, fields):
        """Return a record (a list of "key=value" fields), converted."""
        from scoreboard.parsers import parse_xlog_line

        entry = parse_xlog_line('\t'.join(fields))
        if 'tnntconduct' in entry:
            sys.exit('A record already has a tnntconduct field; is %s '
                     'really an old format?' % entry.get('version'))
        for field, known in self.known_bits.items():
            unknown = entry.get(field, 0) & ~known
            if unknown:
                sys.exit('A record has %s bits 0x%x that the old fixtures '
                         "don't define: %s" % (field, unknown,
                                               '\t'.join(fields)[:200]))

        values = {
            'achieve': entry['achieve'] & ((1 << self.achieve_bits) - 1),
            'conduct': 0,
            'tnntconduct': 0,
        }
        for (field, bit), (new_field, new_bit) in self.conducts.items():
            if new_field != 'achieve' and entry[field] >> bit & 1:
                values[new_field] |= 1 << new_bit
        tnntachieve = [0] * self.tnntachieve_fields
        for (field, bit), (new_field, new_bit) in self.achievements.items():
            if entry.get(field, 0) >> bit & 1:
                index = int(TNNTACHIEVE_FIELD.fullmatch(new_field).group(1))
                tnntachieve[index] |= 1 << new_bit
        for (field, bit), define in self.dropped.items():
            if entry.get(field, 0) >> bit & 1:
                self.dropped_seen[define] += 1

        converted = []
        for field in fields:
            key = field.partition('=')[0]
            if TNNTACHIEVE_FIELD.fullmatch(key):
                continue
            if key == 'version':
                field = 'version=%s' % GAME_VERSION
            elif key == 'deathdnum':
                try:
                    field = 'deathdnum=%d' % self.dungeons[entry[key]]
                except IndexError:
                    sys.exit('A record has deathdnum=%d, which the old game '
                             'did not have' % entry[key])
            elif key in values:
                field = '%s=0x%x' % (key, values[key])
            converted.append(field)
            if key == 'achieve':
                converted.append('tnntconduct=0x%x' % values['tnntconduct'])
        converted.extend('tnntachieve%d=0x%x' % item
                         for item in enumerate(tnntachieve))
        return converted


def make_converter(year):
    """
    Return a RecordConverter for the year's archive, or None if its
    records are already in the current game's format.
    """
    old_format = OLD_FORMATS.get(year)
    if old_format is None:
        return None
    converter = RecordConverter(old_format,
                                bit_positions(old_format['fixtures']),
                                bit_positions())
    print(converter.describe())
    return converter


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


def write_test_file(path, server, picks, rng, converter=None):
    """
    Hand the picked games to the server's test players, convert them if
    there is a converter, and write them.
    """
    from scoreboard.models import is_scummed
    from scoreboard.parsers import parse_xlog_line

    rng.shuffle(picks)
    records = []
    per_player = Counter()
    offset = 0
    for name, size in zip(USERS[server],
                          player_sizes(len(picks), len(USERS[server]))):
        for entry, fields in picks[offset:offset + size]:
            if converter:
                fields = converter.convert(fields)
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

    # categories are those the games were picked by; the rest describes
    # the records as written
    categories = Counter(category(entry) for entry, _ in records)
    written = [parse_xlog_line(line) for _, line in records]
    print('%s: %d games' % (path, len(records)))
    print('  by category: %s' % ', '.join(
        '%s %d' % (name, categories[name]) for name, _ in TARGETS))
    print('  with any achievement bits: %d, scummed: %d' % (
        sum(1 for entry in written if has_achievements(entry)),
        sum(1 for entry in written if is_scummed(entry))))
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
    converter = make_converter(args.year)
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
                        picks, rng, converter)

    if converter and converter.dropped_seen:
        print('Achievements dropped (games): %s' % ', '.join(
            '%s %d' % item for item in sorted(converter.dropped_seen.items())))


if __name__ == '__main__':
    main()
