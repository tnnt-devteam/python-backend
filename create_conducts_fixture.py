#!/usr/bin/env python3
"""
create_conducts_fixture.py - Rebuild conducts.yaml from the game source

Usage: ./create_conducts_fixture.py [--game-dir DIR] [--out FILE] [--check]

The scoreboard decodes conducts by bit position out of the xlogfile's
"conduct" field, and those positions are decided by encodeconduct() in
the game's src/topten.c. A vanilla merge can insert a bit and silently
shift every conduct after it, which is what the NetHack 5.0 merge did in
June 2026: it added the vanilla Sokoban and pets bits at 12 and 13 and
moved every TNNT conduct up, so the fixture decoded the wrong conducts.

This script reads the bit positions back out of encodeconduct() and
writes the fixture. The names and shortnames are the scoreboard's own, so
they live in CONDUCTS below, keyed by the C expression that sets each
bit; a bit mapped to None is one the scoreboard deliberately does not
track. A mismatch between the table and the source is a hard error rather
than a silently wrong fixture, so run this (or --check) after every
vanilla merge.

Achievements have their own generator in the game repository,
util/tnnt_ach_to_yaml.c, which writes scoreboard/fixtures/achievements.yaml
directly:

    cd <game>/util && gcc -I../include -o tnnt_ach_to_yaml \\
        tnnt_ach_to_yaml.c && ./tnnt_ach_to_yaml
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
CONDUCTS = [
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
    ('u.uroleplay.deaf',        ('Permadeaf', 'deaf')),
    ('u.uroleplay.hallu',       ('Permahallucinating', 'halu')),
    ('u.uroleplay.numbones',    ('Bonesless', 'bone')),
    ('u.uconduct.container',    ('Containerless', 'cont')),
    ('u.uconduct.zaps',         ('Zapless', 'zap')),
    ('u.uconduct.potionuse',    ('Potionless', 'pot')),
]

# Two conducts the game reports in the "achieve" field instead. Vanilla
# keeps ACH_BLND and ACH_NUDE as achievements; TNNT treats them as
# conducts. Their positions come from the vanilla achievement enum
# (ACH_BLND = 13 and ACH_NUDE = 14 set bits 12 and 13).
ACHIEVE_CONDUCTS = [(12, 'Zen', 'zen'), (13, 'Nudist', 'nude')]

COMMENT = ('# mumble grumble devteam putting conducts in the achieve field'
           ' grumble mumble...')


def parse_encodeconduct(topten):
    """Return [(bit, condition)] in the order encodeconduct() sets them."""
    try:
        source = topten.read_text(encoding='utf-8', errors='replace')
    except OSError as err:
        sys.exit('cannot read %s: %s' % (topten, err))
    body = re.search(r'\nencodeconduct\(void\)\n\{(.*?)\n\}\n', source, re.S)
    if not body:
        sys.exit('cannot find encodeconduct() in %s' % topten)
    # drop comments, so their text cannot be read as a condition
    text = re.sub(r'/\*.*?\*/', '', body.group(1), flags=re.S)
    return [(int(bit), ' '.join(cond.split()))
            for cond, bit in re.findall(
                r'if \((.*?)\)\s*e \|= 1L << (\d+);', text, re.S)]


def build_rows(bits, verbose):
    """Pair each bit with its scoreboard conduct, checking the source."""
    if len(bits) != len(CONDUCTS):
        sys.exit('encodeconduct() sets %d bits but CONDUCTS has %d entries; '
                 'the game added or removed a conduct and this table needs '
                 'updating' % (len(bits), len(CONDUCTS)))
    if [bit for bit, _ in bits] != list(range(len(bits))):
        sys.exit('encodeconduct() bits are not consecutive from 0: %s'
                 % [bit for bit, _ in bits])
    rows = []
    for (bit, cond), (fragment, names) in zip(bits, CONDUCTS):
        if fragment not in cond:
            sys.exit('bit %d is set by %r, which does not mention %r; the '
                     'conduct order changed and CONDUCTS needs updating'
                     % (bit, cond, fragment))
        if verbose:
            print('%3d  %-38s %s'
                  % (bit, '%s (%s)' % names if names else '-- not tracked --',
                     cond[:60]))
        if names:
            rows.append((bit, names[0], names[1]))
    return rows


def render(rows):
    """Render the fixture."""
    lines = []
    for field, entries in (('conduct', rows),
                           ('achieve', ACHIEVE_CONDUCTS)):
        if field == 'achieve':
            lines.append(COMMENT)
        for bit, name, shortname in entries:
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

    topten = args.game_dir / 'src' / 'topten.c'
    rows = build_rows(parse_encodeconduct(topten), not args.check)
    fixture = render(rows)

    if args.check:
        try:
            current = args.out.read_text(encoding='utf-8')
        except OSError as err:
            sys.exit('cannot read %s: %s' % (args.out, err))
        if current == fixture:
            print('%s is up to date with %s' % (args.out, topten))
            return
        sys.exit('%s is STALE; rerun without --check' % args.out)

    try:
        args.out.write_text(fixture, encoding='utf-8')
    except OSError as err:
        sys.exit('cannot write %s: %s' % (args.out, err))
    print('\nwrote %s: %d conducts (%d in conduct, %d in achieve)'
          % (args.out, len(rows) + len(ACHIEVE_CONDUCTS), len(rows),
             len(ACHIEVE_CONDUCTS)))


if __name__ == '__main__':
    main()
