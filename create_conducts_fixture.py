#!/usr/bin/env python3
"""
create_conducts_fixture.py - Rebuild conducts.yaml from the game source

Usage: ./create_conducts_fixture.py [--game-dir DIR] [--out FILE] [--check]

The scoreboard decodes conducts by bit position out of two xlogfile
fields, and the game decides those positions:

    conduct      encodeconduct() in src/topten.c (vanilla's conducts)
    tnntconduct  encode_tnnt_conducts() in src/tnnt.c (TNNT's conducts,
                 plus the vanilla roleplay options vanilla does not put
                 in "conduct")

A vanilla merge can insert a bit and silently shift every conduct after
it, which is what the NetHack 5.0 merge did in June 2026: it added the
vanilla Sokoban and pets bits at 12 and 13 and moved every TNNT conduct
up, so the fixture decoded the wrong conducts. In October 2026 the TNNT
conducts outgrew the 32-bit "conduct" field and moved to "tnntconduct".

This script reads the bit positions back out of both functions and
writes the fixture. The names and shortnames are the scoreboard's own,
so they live in the tables below, keyed by the C expression that sets
each bit; a bit mapped to None is one the scoreboard deliberately does
not track. A mismatch between a table and the source is a hard error
rather than a silently wrong fixture, so run this (or --check) after
every change to either function, including every vanilla merge.

Achievements have their own generator in the game repository,
util/tnnt_ach_to_yaml.c. Rebuild it and the fixture with:

    cd <game>/util && make tnnt_ach_to_yaml && \\
        ./tnnt_ach_to_yaml > tnnt_achievements.yaml
    cd <this repo> && ./ach_to_yaml.sh <game> \\
        > scoreboard/fixtures/achievements.yaml
"""

import argparse
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_GAME_DIR = Path('/home/build/tnnt')
DEFAULT_OUT = BASE_DIR / 'scoreboard' / 'fixtures' / 'conducts.yaml'

# The bits of the xlogfile "conduct" field, in the order encodeconduct()
# sets them: a fragment of the C condition -> (name, shortname), or None
# for a bit the scoreboard does not track.
VANILLA_CONDUCTS = [
    ('u.uconduct.food',         ('Foodless', 'food')),
    ('u.uconduct.unvegan',      ('Vegan', 'vgn')),
    ('u.uconduct.unvegetarian', ('Vegetarian', 'veg')),
    ('u.uconduct.gnostic',      ('Atheist', 'athe')),
    ('u.uconduct.weaphit',      ('Weaponless', 'weap')),
    ('u.uconduct.killer',       ('Pacifist', 'paci')),
    ('u.uconduct.literate',     ('Illiterate', 'illi')),
    ('u.uconduct.polypiles',    ('Polypileless', 'pile')),
    ('u.uconduct.polyselfs',    ('Polyselfless', 'self')),
    ('u.uconduct.wishes',       ('Wishless', 'wish')),
    ('u.uconduct.wisharti',     ('Artiwishless', 'artw')),
    ('num_genocides()',         ('Genocideless', 'geno')),
    # vanilla's "obeyed Sokoban rules"; the scoreboard has never had a
    # conduct for it, and adding one would also change what the "preserve
    # each conduct" trophy demands
    ('u.uconduct.sokocheat',    None),
    ('u.uconduct.pets',         ('Petless', 'pets')),
]

# The same for the "tnntconduct" field and encode_tnnt_conducts(). Its
# bits need not be consecutive: the game keeps the vanilla roleplay
# options (pauper, deaf) at the top of the field, so that they can be
# dropped if vanilla ever reports them in "conduct", without moving the
# TNNT conducts below them.
TNNT_CONDUCTS = [
    ('u.uconduct.elbereth',     ('Elberethless', 'elbe')),
    ('u.umortality',            ('Survivor', 'surv')),
    ('u.uconduct.rmswapchest',  ('Swapchestless', 'swap')),
    ('gu.urole.neminum',        ('Never kill a quest nemesis', 'neme')),
    ('PM_VLAD_THE_IMPALER',     ('Never kill Vlad', 'vlad')),
    ('PM_WIZARD_OF_YENDOR',     ('Never kill the Wizard of Yendor', 'wiz')),
    ('PM_HIGH_CLERIC',          ('Never kill the High Priest of Moloch',
                                 'prst')),
    ('PM_DEATH',                ('Never kill a Rider', 'ride')),
    ('u.uconduct.artitouch',    ('Artifactless', 'arti')),
    ('u.uroleplay.hallu',       ('Permahallucinating', 'halu')),
    ('u.uroleplay.numbones',    ('Bonesless', 'bone')),
    ('u.uconduct.container',    ('Containerless', 'cont')),
    ('u.uconduct.zaps',         ('Zapless', 'zap')),
    ('u.uconduct.potionuse',    ('Potionless', 'pot')),
    ('u.uconduct.identifies',   ('Identificationless', 'iden')),
    ('u.uconduct.gained_refl',  ('Reflectionless', 'refl')),
    ('u.uconduct.gained_mr',    ('Magic-resistance-less', 'mr')),
    ('u.uconduct.usedmoney',    ('Moneyless', 'gold')),
    ('u.uroleplay.pauper',      ('Pauper', 'paup')),
    ('u.uroleplay.deaf',        ('Permadeaf', 'deaf')),
]

# Each conduct field: (xlogfield, C function, source file under the game
# directory, table, whether its bits must run 0, 1, 2, ... with no gap).
FIELDS = [
    ('conduct', 'encodeconduct', 'src/topten.c', VANILLA_CONDUCTS, True),
    ('tnntconduct', 'encode_tnnt_conducts', 'src/tnnt.c', TNNT_CONDUCTS,
     False),
]

# Two conducts the game reports in the "achieve" field instead. Vanilla
# keeps ACH_BLND and ACH_NUDE as achievements; TNNT treats them as
# conducts. Their positions come from the vanilla achievement enum
# (ACH_BLND = 13 and ACH_NUDE = 14 set bits 12 and 13).
ACHIEVE_CONDUCTS = [(12, 'Zen', 'zen'), (13, 'Nudist', 'nude')]

COMMENT = ('# mumble grumble devteam putting conducts in the achieve field'
           ' grumble mumble...')

# The game writes each field with "0x%lx" from a long, i.e. 64 bits.
MAX_BIT = 63


def parse_encoder(path, function):
    """Return [(bit, condition)] in the order `function` sets them."""
    try:
        source = path.read_text(encoding='utf-8', errors='replace')
    except OSError as err:
        sys.exit('cannot read %s: %s' % (path, err))
    body = re.search(r'\n%s\(void\)\n\{(.*?)\n\}\n' % re.escape(function),
                     source, re.S)
    if not body:
        sys.exit('cannot find %s() in %s' % (function, path))
    # drop comments, so their text cannot be read as a condition
    text = re.sub(r'/\*.*?\*/', '', body.group(1), flags=re.S)
    return [(int(bit), ' '.join(cond.split()))
            for cond, bit in re.findall(
                r'if \((.*?)\)\s*e \|= 1L << (\d+);', text, re.S)]


def build_rows(function, bits, table, consecutive, verbose):
    """Pair each bit with its scoreboard conduct, checking the source."""
    if len(bits) != len(table):
        sys.exit('%s() sets %d bits but its table has %d entries; the game '
                 'added or removed a conduct and this table needs updating'
                 % (function, len(bits), len(table)))
    positions = [bit for bit, _ in bits]
    if consecutive and positions != list(range(len(bits))):
        sys.exit('%s() bits are not consecutive from 0: %s'
                 % (function, positions))
    if len(set(positions)) != len(positions) or max(positions) > MAX_BIT:
        sys.exit('%s() sets a bit twice or past bit %d: %s'
                 % (function, MAX_BIT, positions))
    rows = []
    for (bit, cond), (fragment, names) in zip(bits, table):
        if fragment not in cond:
            sys.exit('%s() sets bit %d with %r, which does not mention %r; '
                     'the conduct order changed and its table needs updating'
                     % (function, bit, cond, fragment))
        if verbose:
            print('%3d  %-38s %s'
                  % (bit, '%s (%s)' % names if names else '-- not tracked --',
                     cond[:60]))
        if names:
            rows.append((bit, names[0], names[1]))
    return rows


def render(fields):
    """Render the fixture from [(xlogfield, rows)]."""
    lines = []
    for field, rows in fields + [('achieve', ACHIEVE_CONDUCTS)]:
        if field == 'achieve':
            lines.append(COMMENT)
        for bit, name, shortname in rows:
            lines += ['- model: scoreboard.conduct',
                      '  fields:',
                      '    name: %s' % name,
                      '    shortname: %s' % shortname,
                      '    xlogfield: %s' % field,
                      '    bit: %d' % bit]
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(
        description='Rebuild conducts.yaml from the game source.')
    parser.add_argument('--game-dir', type=Path, default=DEFAULT_GAME_DIR,
                        help='the TNNT game repository '
                             '(default: %(default)s)')
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT,
                        help='where to write it (default: the fixture)')
    parser.add_argument('--check', action='store_true',
                        help='do not write; exit 1 if the fixture is stale')
    args = parser.parse_args()

    fields = []
    for field, function, source, table, consecutive in FIELDS:
        if not args.check:
            print('%s (%s() in %s):' % (field, function, source))
        bits = parse_encoder(args.game_dir / source, function)
        fields.append((field, build_rows(function, bits, table, consecutive,
                                         not args.check)))
    all_names = [row[1:] for _, rows in fields for row in rows]
    all_names += [row[1:] for row in ACHIEVE_CONDUCTS]
    for i in (0, 1):
        names = [entry[i] for entry in all_names]
        if len(set(names)) != len(names):
            sys.exit('a conduct %s is used twice: %s'
                     % (('name', 'shortname')[i], sorted(names)))
    fixture = render(fields)

    if args.check:
        try:
            current = args.out.read_text(encoding='utf-8')
        except OSError as err:
            sys.exit('cannot read %s: %s' % (args.out, err))
        if current == fixture:
            print('%s is up to date with %s' % (args.out, args.game_dir))
            return
        sys.exit('%s is STALE; rerun without --check' % args.out)

    try:
        args.out.write_text(fixture, encoding='utf-8')
    except OSError as err:
        sys.exit('cannot write %s: %s' % (args.out, err))
    print('\nwrote %s: %d conducts (%s, %d in achieve)'
          % (args.out, len(all_names),
             ', '.join('%d in %s' % (len(rows), field)
                       for field, rows in fields),
             len(ACHIEVE_CONDUCTS)))


if __name__ == '__main__':
    main()
