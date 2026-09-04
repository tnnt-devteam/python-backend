from django.core.management.base import BaseCommand
from scoreboard.models import (
    Game, Player, Clan, Trophy, Achievement, Conduct, SCUMMED_GAME_Q
)
# Imported by name so that they are also attributes of this module.
from scoreboard.trophy_defs import (
    TOTAL_GENDERS, TOTAL_ALIGNMENTS, TOTAL_RACES, TOTAL_ROLES,
    TOTAL_POSSIBLE_COMBOS, great_lesser_race, great_lesser_role
)
from django.db import transaction
from django.db.models import Sum, Min, Max, Count
from tnnt import settings
from tnnt import uniqdeaths
from tnnt.trophy_grid import invalidate_trophy_grid_cache
from pathlib import Path
from urllib.parse import urlparse
from collections import Counter
import os
import re
import logging
import requests
from decimal import Decimal

logger = logging.getLogger() # root logger

# Fixture-backed data that doesn't change over the lifetime of the tournament.
# Loaded once per run by load_static_data(), which handle() calls first thing,
# rather than at import time: importing this module then has no database side
# effects (tests load their fixtures first, then call load_static_data()).
ALL_ACHIEVEMENTS = []
TOTAL_ACHIEVEMENTS = 0
TOTAL_CONDUCTS = 0
TROPHIES = {}
UNIQ_ACHFIELDS = 0

# Timeout for fetching donor files: (connect, read) seconds.
DONOR_TIMEOUT = (10, 30)

def load_static_data():
    global ALL_ACHIEVEMENTS, TOTAL_ACHIEVEMENTS, TOTAL_CONDUCTS
    global TROPHIES, UNIQ_ACHFIELDS
    ALL_ACHIEVEMENTS = list(Achievement.objects.all())
    TOTAL_ACHIEVEMENTS = len(ALL_ACHIEVEMENTS)
    TOTAL_CONDUCTS = Conduct.objects.count()
    TROPHIES = { tr.name: tr for tr in Trophy.objects.all() }
    UNIQ_ACHFIELDS = len(set([ach.xlogfield for ach in ALL_ACHIEVEMENTS]))

def donor_cache_path(url):
    # Where the last successfully fetched copy of the donor file at `url` is
    # kept, next to the xlogfiles.
    return Path(settings.XLOG_DIR) / ('donors.%s' % urlparse(url).hostname)

def fetch_donor_names():
    '''
    Download every donor file in settings.DONOR_FILES and return a Counter
    of player names: one count per line, i.e. per item someone else took
    out of the swap chest.

    A file that can't be fetched falls back to the last copy that was
    fetched successfully (kept under XLOG_DIR), with a warning. If there is
    no such copy either, that server's donations are missing from this run
    but the other servers' are still counted. (Zeroing everyone and giving
    up, which is what a hard failure used to do, is worse than either.)

    Up to K2 whether it is better in the long run to request these files via
    HTTP or sync them over to the webserver and read them locally.
    '''
    names = Counter()
    for url in settings.DONOR_FILES:
        cache = donor_cache_path(url)
        body = None
        try:
            r = requests.get(url, timeout=DONOR_TIMEOUT)
            if r.status_code == 200:
                body = r.content
                try:
                    cache.write_bytes(body)
                except OSError as e:
                    logger.warning('Could not save a copy of donor file %s '
                                   'at %s: %s', url, cache, e)
            else:
                logger.error('Could not fetch donor file %s - HTTP %d',
                             url, r.status_code)
        except requests.RequestException as e:
            logger.error('Could not fetch donor file %s - %s', url, e)
        if body is None:
            try:
                body = cache.read_bytes()
                logger.warning('Using the last good copy of donor file %s '
                               'from %s', url, cache)
            except OSError:
                logger.error('No saved copy of donor file %s either; its '
                             'donations are not counted this run', url)
                continue
        for line in body.decode('utf-8', errors='replace').splitlines():
            plname = line.strip()
            if plname:
                names[plname] += 1
    return names

@transaction.atomic
def apply_donor_counts(names):
    # Donation credits are recomputed from scratch every run, so first wipe
    # them from everyone (one UPDATE, not one save() per Player).
    Player.objects.update(donations=0)
    for plname, count in names.items():
        updated = Player.objects.filter(name=plname).update(donations=count)
        if not updated:
            # It is possible for there to be a donor for which a Player
            # doesn't exist yet, specifically in their first game if
            # they HAVE NOT logged into the site yet but HAVE put items
            # into the swap chest, and someone else has already removed
            # those items. Like in the temporary achievements case, we
            # ignore this until a later update in which the Player does
            # exist.
            #
            # NOTE: This works because the donor files are re-read in full
            # every run. If that ever changes to an xlogfile-like system
            # that stores a file position, such donors WOULD be lost and
            # this SHOULD create the Player instead.
            logger.warning('Ignoring nonexistent donor %s', plname)

def populateDonors():
    # Network first, outside any transaction; then one short atomic write.
    apply_donor_counts(fetch_donor_names())

# Gather temporary achievements. This only needs to happen once per aggregation
# and should happen BEFORE any aggregating is done.
# Input: files in TEMP_ACHIEVEMENTS_PATH, one per game in progress, named
# <player>.tach[.<server>].txt and containing the tnntachieve0..N bitfields as
# hex, one per line.
# Output: Player.temp_achievements is rebuilt from those files.
@transaction.atomic
def obtainTempAchievements():
    tach_dir = getattr(settings, 'TEMP_ACHIEVEMENTS_PATH', None)
    if tach_dir is None:
        # having no TEMP_ACHIEVEMENTS_PATH in settings indicates you don't want
        # to show these
        return

    # Unconditionally wipe all temporary achievements from everyone. If someone
    # still has some from the same game in progress, the file will still be
    # there and we'll read it in after this. One DELETE on the join table
    # rather than a clear() and a pointless save() per Player.
    Player.temp_achievements.through.objects.all().delete()

    # process only files matching the temp achievement filename format, so it
    # won't try to read log files, etc
    fn_pat = re.compile(r".*\.tach(?:\.(au|eu|us))?\.txt$")
    try:
        filelist = [ fn for fn in os.listdir(Path(tach_dir))
                    if fn_pat.fullmatch(fn) ]
    except OSError as e:
        logger.error('Cannot list temp achievements directory %s: %s',
                     tach_dir, e)
        return

    for fname in filelist:
        plname = fname.split('.')[0]
        try:
            player = Player.objects.get(name=plname)
        except Player.DoesNotExist:
            # If there is a player who appears here but does not exist in the
            # database, that's fine - they may not have completed their first
            # game yet or logged in on the site. Ignore them.
            logger.info('Ignoring temp achievements from file %s - nonexistent player'
                        % (fname))
            continue

        # don't call player.temp_achievements.clear() before each file (as we
        # previously did), so files from simultaneous games on multiple servers
        # are additive, instead of only showing the last one in the list.

        try:
            with open(Path(tach_dir) / fname, 'r') as file:
                lines = file.readlines()
        except FileNotFoundError:
            # File was deleted between directory listing and open (TOCTOU).
            # This is expected in multi-process environments where games
            # end and temp achievement files are removed. Skip and continue.
            logger.info('Ignoring temp achievements from file %s - '
                        'file deleted during processing' % (fname))
            continue
        except OSError as e:
            logger.warning('Skipping temp ach file %s: %s', fname, e)
            continue

        if len(lines) != UNIQ_ACHFIELDS:
            logger.warning('Temp ach file %s is malformed with wrong number of lines'
                           % (fname))
            continue # for fname in filelist

        # create a dict of { tnntachieve0: <achieve bits>, tnntachieve1: ... }
        # Assumption: file contents have tnntachieve0 as a number on the
        # first line, then subsequent lines are tnntachieve1, tnntachieve2, ...
        try:
            achdict = { 'tnntachieve%d' % i: int(L, 16)
                        for i, L in enumerate(lines) }
            achs = [ ach for ach in ALL_ACHIEVEMENTS
                     if achdict[ach.xlogfield] & (1 << ach.bit) ]
        except (ValueError, KeyError) as e:
            # A line that isn't a hex number (the game may still be writing
            # the file), or an achievement whose xlog field the file doesn't
            # have. Either way, skip just this file.
            logger.warning('Skipping malformed temp ach file %s: %s', fname, e)
            continue
        if achs:
            player.temp_achievements.add(*achs)

# Determine and award trophies to a player or clan.
# ASSUMPTION: The player's LeaderboardBaseFields are already computed.
# allgames_qs is a QuerySet of all Games by this player/clan. For most
# operations, we convert this to a list to avoid thrashing the database too
# much, while keeping the queryset around for the few things that need it. (I'm
# not totally sure if this would actually do that with repeated queries, but I
# suspect it would.)
# IMPORTANT: Nothing in here should use gender or align! gender0 and align0 only!
def awardTrophies(player_or_clan, allgames_qs):
    # First, a small optimization: exclude all games that are neither ascensions
    # nor have mines/soko complete. These won't contribute to any trophies.
    # (Never Scum a Game is based off the precomputed games_scummed.)
    allgames = [ g for g in allgames_qs.all() if g.won or g.mines_soko ]

    # It might be possible to optimize some of this by doing a big, single pass
    # through allgames and storing various bits of data in sets, but there
    # currently isn't a demonstrated need for this.

    # Great Race
    for fullrace, details in great_lesser_race.items():
        # Compute all distinct roles for which there exists a winning game
        # that has this race. If the trophy required set is a subset of it,
        # award it.
        # This uses a subset operation because the player's human ascensions can
        # be a larger set than what is required for Great Human. (I.e. it
        # shouldn't be assumed that the requisite lists above contain every
        # possible ascendable combination in NetHack, which also goes for Great
        # Role.)
        if details['req_roles'].issubset(set(g.role for g in allgames
                                         if g.won and g.race == details['race'])):
            player_or_clan.trophies.add(TROPHIES['Great %s' % fullrace])

        # Then the same for mines_soko games.
        if details['req_roles'].issubset(set(g.role for g in allgames
                                         if g.mines_soko and g.race == details['race'])):
            player_or_clan.trophies.add(TROPHIES['Lesser %s' % fullrace])

    # Great Role
    for fullrole, details in great_lesser_role.items():
        # Similar to above. Compute distinct race-align combos.
        if details['req_race_algn'].issubset(set('%s-%s' % (g.race, g.align0) for g in allgames
                                             if g.won and g.role == details['role'])):
            player_or_clan.trophies.add(TROPHIES['Great %s' % fullrole])

        # And the same for mines_soko.
        if details['req_race_algn'].issubset(set('%s-%s' % (g.race, g.align0) for g in allgames
                                             if g.mines_soko and g.role == details['role'])):
            player_or_clan.trophies.add(TROPHIES['Lesser %s' % fullrole])

    # All Foo
    if len(set(g.gender0 for g in allgames if g.won)) == TOTAL_GENDERS:
        player_or_clan.trophies.add(TROPHIES['Both Genders'])
    if len(set(g.align0 for g in allgames if g.won)) == TOTAL_ALIGNMENTS:
        player_or_clan.trophies.add(TROPHIES['All Alignments'])
    if len(set(g.race for g in allgames if g.won)) == TOTAL_RACES:
        player_or_clan.trophies.add(TROPHIES['All Races'])
    if len(set(g.role for g in allgames if g.won)) == TOTAL_ROLES:
        player_or_clan.trophies.add(TROPHIES['All Roles'])
    if player_or_clan.unique_achievements == TOTAL_ACHIEVEMENTS:
        player_or_clan.trophies.add(TROPHIES['All Achievements'])
    # All Conducts kind of has to be a query, since we don't track "number of
    # discrete conducts across all games" on a leaderboard.
    unique_conducts = allgames_qs.filter(won=True) \
        .aggregate(Count('conducts__id', distinct=True)) \
        ['conducts__id__count']
    if unique_conducts == TOTAL_CONDUCTS:
        player_or_clan.trophies.add(TROPHIES['All Conducts'])
    if player_or_clan.unique_ascs == TOTAL_POSSIBLE_COMBOS:
        player_or_clan.trophies.add(TROPHIES['NetHack Master'])
        if unique_conducts == TOTAL_CONDUCTS:
            player_or_clan.trophies.add(TROPHIES['NetHack Dominator'])

    # Never Scum a Game is a weird trophy in that a player has it by default,
    # and can lose it at a later point.
    try:
        nsag = player_or_clan.trophies.get(name='Never Scum a Game')
        if player_or_clan.games_scummed > 0:
            player_or_clan.trophies.remove(nsag)
    except Trophy.DoesNotExist:
        if player_or_clan.total_games > 0 and player_or_clan.games_scummed == 0:
            player_or_clan.trophies.add(TROPHIES['Never Scum a Game'])

    # Never Kill Foo
    for g in allgames_qs.filter(won=True).prefetch_related('conducts'):
        for c in g.conducts.all():
            if c.shortname == 'neme':
                player_or_clan.trophies.add(TROPHIES['Keep Your Nemesis Alive'])
            elif c.shortname == 'vlad':
                player_or_clan.trophies.add(TROPHIES['Keep Vlad Alive'])
            elif c.shortname == 'wiz':
                player_or_clan.trophies.add(TROPHIES['Keep Rodney Alive'])
            elif c.shortname == 'prst':
                player_or_clan.trophies.add(TROPHIES['Keep The High Priest of Moloch Alive'])
            elif c.shortname == 'ride':
                player_or_clan.trophies.add(TROPHIES['Keep The Riders Alive'])

# Given a QuerySet of Games, compute the overall Z-score of the winning games.
# (Does not assume the games are all wins.)
def computeZscore(game_qs):
    zscore = Decimal(0.0)
    roledict = {}
    for g in game_qs:
        if not g.won:
            continue
        if not g.role in roledict:
            roledict[g.role] = 0
        roledict[g.role] += 1
        zscore += 1 / Decimal(roledict[g.role])
    return zscore

# Compute LeaderboardBaseFields data on all Players, and write it back.
def aggregatePlayerData():
    for plr in Player.objects.all():
        # all of the below only consider games done by this player
        gamesby_plr = Game.objects.filter(player=plr)
        # and a number of them only consider *ascended* games
        winsby_plr = gamesby_plr.filter(won=True)

        # simple aggregates (game counts)
        plr.total_games = gamesby_plr.count()
        plr.wins = winsby_plr.count()
        plr.splats = gamesby_plr.filter(splatted=True).count()
        plr.games_over_1000_turns = gamesby_plr.filter(turns__gte=1000).count()
        # "What is a scummed game" is defined once, in scoreboard.models
        # (SCUMMED_GAME_Q: quit or escaped with <= 100 turns); this field is
        # the precomputed result every page should use.
        plr.games_scummed = gamesby_plr.filter(SCUMMED_GAME_Q).count()

        # a more complex aggregate
        # different from max_achieves_game; this is the total number of
        # distinct achievements across all games
        plr.unique_achievements = \
                gamesby_plr.aggregate(Count('achievements__id', distinct=True)) \
                ['achievements__id__count']

        # Unique deaths are more complex, but that's outsourced to another
        # module, so just get the set of unique deaths and take the length.
        plr.unique_deaths = len(uniqdeaths.compile_unique_deaths(gamesby_plr))

        # Unique ascs are a one-liner.
        plr.unique_ascs = len(set(g.rrga() for g in winsby_plr))

        # Z-scoring can't be done by simple reduction to a set, though.
        plr.zscore = computeZscore(winsby_plr)

        # Streaks are computed on their own as well.
        streak_lengths = list(map(lambda s: len(s.games), plr.get_streaks()))
        if len(streak_lengths) == 0:
            plr.longest_streak = 0
        else:
            plr.longest_streak = max(streak_lengths)

        # From here on, this is less about aggregating into one result, and more
        # about taking the game which is the player's best in some statistic.
        # Skip this if the player has no games, and for most of them, if the
        # player has no wins.
        if plr.total_games > 0:
            plr.max_score_game = gamesby_plr.order_by('-points')[0]
            if plr.wins > 0:
                plr.min_score_asc = winsby_plr.order_by('points')[0]
                plr.lowest_turncount_asc = winsby_plr.order_by('turns')[0]
                plr.fastest_realtime_asc = winsby_plr.order_by('wallclock')[0]
                plr.first_asc = winsby_plr.earliest('endtime')

            # These two are also Games which are the player's best in a
            # statistic, but require a bit more complex of a query.
            plr.max_achieves_game = \
                gamesby_plr.annotate(nachieve=Count('achievements__id', distinct=True)) \
                .order_by('-nachieve')[0]
            # post 2021 TODO: Should this exclude some TNNT-added conducts?
            if plr.wins > 0:
                plr.max_conducts_asc = \
                    winsby_plr.annotate(ncond=Count('conducts__id', distinct=True)) \
                    .order_by('-ncond')[0]

        plr.save()
        awardTrophies(plr, gamesby_plr)
    logger.info('aggregatePlayerData complete')

# Compute LeaderboardBaseFields data on all Clans, and write it back.
# ASSUMPTION: It is run after aggregatePlayerData is run, and that each Player
# has had its leaderboard base fields updated.
def aggregateClanData():
    for clan in Clan.objects.all():
        clan_plrs = Player.objects.filter(clan=clan)

        # Basic aggregations can be computed pretty easily from the Players.
        aggrs_dict = clan_plrs.aggregate(Sum('total_games'),
                                         Sum('wins'),
                                         Sum('games_over_1000_turns'),
                                         Sum('games_scummed'),
                                         Max('longest_streak'),
                                         Sum('splats'),
                                         Sum('donations'))
        clan.total_games = aggrs_dict['total_games__sum']
        clan.wins = aggrs_dict['wins__sum']
        clan.games_over_1000_turns = aggrs_dict['games_over_1000_turns__sum']
        clan.games_scummed = aggrs_dict['games_scummed__sum']
        clan.longest_streak = aggrs_dict['longest_streak__max']
        clan.splats = aggrs_dict['splats__sum']
        clan.donations = aggrs_dict['donations__sum']

        # Unfortunately, we have to do a rather nasty multiple join to get the
        # total number of distinct achievements earned collectively by all the
        # clan members. It's still better than getting and combining sets of all
        # the achievement titles, though.
        clan.unique_achievements = \
                clan_plrs.aggregate(Count('game__achievements__id', distinct=True)) \
                ['game__achievements__id__count']

        # Unique deaths for the clan requires constructing a QuerySet of all
        # games played by clan members.
        gamesby_clan = Game.objects.filter(player__clan=clan)
        winsby_clan = gamesby_clan.filter(won=True)

        clan.unique_deaths = len(uniqdeaths.compile_unique_deaths(gamesby_clan))
        clan.zscore = computeZscore(winsby_clan)

        # Unique ascs are still a one-liner.
        clan.unique_ascs = len(set(g.rrga() for g in gamesby_clan if g.won))

        # And then back to a (somewhat) simpler model, in which the clan can
        # just pick fields off its precomputed members.
        # As with players, skip this if the clan has no games.
        if clan.wins > 0:
            # the pattern:
            # - join on the player's best Game in this stat
            # - order them by that stat
            # - pick the first Player from the resulting set
            # - set the clan leaderboard field to the corresponding Player field
            # This works nicely because even if all of the players in the clan
            # have a null instead of a Game for this field, it doesn't crash -
            # it instead just returns a None, which is correct - the clan has no
            # qualifying games for that stat.
            # The [0] reference should be fine - only way that would error is if
            # the clan had no members.
            clan.min_score_asc = clan_plrs.filter(wins__gt=0) \
                .order_by('min_score_asc__points') \
                [0].min_score_asc
            clan.lowest_turncount_asc = clan_plrs.filter(wins__gt=0) \
                .order_by('lowest_turncount_asc__turns') \
                [0].lowest_turncount_asc
            clan.fastest_realtime_asc = clan_plrs.filter(wins__gt=0) \
                .order_by('fastest_realtime_asc__wallclock') \
                [0].fastest_realtime_asc
            clan.first_asc = clan_plrs.filter(wins__gt=0) \
                .earliest('first_asc__endtime').first_asc
            clan.max_conducts_asc = clan_plrs.filter(wins__gt=0) \
                .annotate(ncond=Count('max_conducts_asc__conducts')) \
                .order_by('-ncond') \
                [0].max_conducts_asc

        if clan.total_games > 0:
            # Same as the above block but for stats which don't require wins.
            clan.max_score_game = clan_plrs.filter(total_games__gt=0) \
                .order_by('-max_score_game__points') \
                [0].max_score_game
            clan.max_achieves_game = clan_plrs.filter(total_games__gt=0) \
                .annotate(maxachieve=Count('max_achieves_game__achievements')) \
                .order_by('-maxachieve') \
                [0].max_achieves_game

        clan.save()
        # For clans, we have to remove all trophies before re-awarding them.
        # This is because a member who provided some of the effort towards a
        # trophy may have left since the last aggregation. (This used to be
        # remove() with no arguments, which is a no-op, so clans never lost
        # trophies.)
        clan.trophies.clear()
        awardTrophies(clan, gamesby_clan)
    logger.info('aggregateClanData complete')

class Command(BaseCommand):
    help = 'Compute aggregate data from the set of all games'

    # To be completely accurate and up-to-date, the clan aggregation logic
    # "should" be triggered upon any person entering or leaving a clan.
    #
    # However, that could result in triggering aggregation way too often when
    # clans are fluid early in the tournament, and possibly even exposes it to
    # abuse if someone creates and disbands a clan repeatedly. Since players are
    # generally aware that the site may lag real life by a few minutes and no
    # one is clamoring for us to do just-in-time updates, it remains the most
    # convenient to just keep this as a command that's run at regular intervals.
    def handle(self, *args, **options):
        load_static_data()
        obtainTempAchievements()
        populateDonors()
        # This will end up doing a bunch of writes. Force them to happen all at
        # once with atomic().
        # If this is not done, someone could load a page when e.g. Player writes
        # have gone through but Clan writes have not, and wonder why the person
        # with the new best realtime game doesn't have their clan at the top of
        # the leaderboard. Or any of several similar problems.
        # Temp achievements are done separately because they exist independently
        # from this more important stuff.
        with transaction.atomic():
            aggregatePlayerData()
            aggregateClanData()

        # Invalidate all trophy grid caches after transaction commits. (With
        # the default per-process LocMemCache this can't reach the web
        # server's cache from a cron run; entries expire on their own after
        # TROPHY_GRID_CACHE_TIMEOUT. It does the right thing if a shared
        # backend is ever configured.)
        invalidate_trophy_grid_cache()
