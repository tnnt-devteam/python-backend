from django.views.generic import TemplateView
from django.views import View
from django.contrib.auth.views import LoginView
from django.shortcuts import render, get_object_or_404
from django.db.models import Exists, OuterRef, F, Count, Value, Sum, Q
from django.db.models.functions import TruncSecond
from scoreboard.models import *
from scoreboard.models import SCUMMED_GAME_Q, scummed_q, is_scummed
from scoreboard.api_views import ratelimit_exclude_localhost
from django.utils.decorators import method_decorator
from tnnt.forms import CreateClanForm, InviteMemberForm, SetMessageForm
from django.http import HttpResponse, HttpResponseRedirect
from django.core.cache import cache
from . import hardfought_utils # find_player
from . import dumplog_utils # format_dumplog
from . import admin_utils
from . import settings
from datetime import datetime, timezone
import logging
import re
import sqlite3
from tnnt import uniqdeaths

logger = logging.getLogger() # use root logger

def bulk_upd_games(gamelist, do_conducts):
    # Convenience function (not a view itself) used by multiple views when
    # showing the most recent games or ascensions.
    #
    # Given a list of dicts containing Game fields (specifically 'playername',
    # 'dlg_fmt' and 'starttime'), also insert into each of those dicts:
    #   1) a 'dumplog' field containing the formatted dumplog URL
    #   2) a 'rrga' field of the rol-rac-gen-aln string
    #   3) a 'conducts' field which is an array containing the shortnames of
    #      conducts achieved in that game (if do_conducts is True).
    #

    # If we need conducts, fetch them all at once to avoid doing a separate
    # query for each game
    if do_conducts and gamelist:
        game_ids = [g['id'] for g in gamelist]
        # Fetch all conducts for these games in one query
        conducts_qs = Conduct.objects.filter(game__id__in=game_ids) \
                                     .values('game__id', 'shortname')

        # Group conducts by game_id
        conducts_by_game = {}
        for conduct in conducts_qs:
            game_id = conduct['game__id']
            if game_id not in conducts_by_game:
                conducts_by_game[game_id] = []
            conducts_by_game[game_id].append(conduct['shortname'])

    for g in gamelist:
        # Check if this is a startscum game (no dumplog generated); see
        # scoreboard.models.is_scummed for the definition
        g['is_startscum'] = is_scummed(g)

        g['dumplog'] = dumplog_utils.format_dumplog(g['dlg_fmt'], g['playername'],
                                                    g['starttime'])

        # This is a duplicate of Game.rrga, but we can't call that because the
        # type of g here is not a Game but a dict.
        # Since it's a one-liner, not a big deal to leave it duplicated.
        g['rrga'] = '-'.join([g['role'], g['race'], g['gender0'], g['align0']])

        # Format endtime and starttime to ISO format (YYYY-MM-DD HH:MM)
        if 'endtime' in g and g['endtime']:
            g['endtime'] = g['endtime'].strftime('%Y-%m-%d %H:%M')
        if 'starttime' in g and g['starttime']:
            g['starttime'] = g['starttime'].strftime('%Y-%m-%d %H:%M')

        if do_conducts:
            # Use the pre-fetched conducts instead of querying per game
            g['conducts'] = conducts_by_game.get(g['id'], [])

    return gamelist

# Attempt to get the player linked with this user ID. Contains some
# checks against weird edge cases.
# Argument is request.user from an HTTP request.
# If we seriously can't find a player, raise Player.DoesNotExist; the
# expectation is that the caller will return an appropriate error (500)
# to the browser.
def get_player(request_user):
    # An anonymous visitor has no Player. (Without this check the lookup
    # below would be `user IS NULL`, which matches every Player who has
    # never logged in.)
    if not request_user.is_authenticated:
        raise Player.DoesNotExist
    try:
        return Player.objects.get(user=request_user.id)
    except Player.DoesNotExist:
        logger.warning('No Player found linked to logged-in user (id %s, name %s)',
                       request_user.id, request_user)
        try:
            # ok THIS shouldn't fail... we really shouldn't have allowed a
            # user to exist without a Player of corresponding name
            player = Player.objects.get(name=request_user)
            player.user = request_user
            player.save()
            logger.warning('Fell back on linking to existing Player named %s',
                           request_user)
            return player
        except Player.DoesNotExist as e:
            logger.error('No Player found with name of logged in user (name %s)',
                         request_user)
            raise e

class HomepageView(TemplateView):
    template_name = 'index.html'

    def get_context_data(self, **kwargs):
        # general statistics
        kwargs['numclans'] = Clan.objects.count()
        kwargs['numplayers'] = Player.objects.count()
        kwargs['numgames'] = Game.objects.count()
        aggr = Player.objects.aggregate(
                    Sum('games_scummed'),
                    Sum('wins'),
                    Sum('splats'),
                    Sum('unique_achievements'),
                    Sum('donations'))
        kwargs['numscums'] = aggr['games_scummed__sum']
        kwargs['numascs'] = aggr['wins__sum']
        kwargs['numsplats'] = aggr['splats__sum']
        kwargs['numminessoko'] = Game.objects.filter(mines_soko=True).count()
        kwargs['numascenders'] = Player.objects.filter(wins__gt=0).count()
        kwargs['totachieve'] = aggr['unique_achievements__sum']
        kwargs['totdonations'] = aggr['donations__sum']
        aggr2 = Game.objects.aggregate(Sum('realtime'),
                                       Sum('turns'))
        kwargs['totturns'] = aggr2['turns__sum']
        kwargs['tottime'] = aggr2['realtime__sum']
        kwargs['totuniqdeaths'] = len(uniqdeaths.compile_unique_deaths(Game.objects.all()))

        # last 10 games/wins, leaving out scummed games (see
        # scoreboard.models.SCUMMED_GAME_Q)
        base_qs = Game.objects.exclude(SCUMMED_GAME_Q).annotate(
            playername=F('player__name'),
            dlg_fmt=F('source__dumplog_fmt')).order_by('-endtime')
        kwargs['last10games'] = bulk_upd_games(list(base_qs.values()[:10]), False)
        kwargs['last10wins'] = \
            bulk_upd_games(list(base_qs.filter(won=True).values()[:10]), True)

        return kwargs

class FaqView(TemplateView):
    template_name = 'faq.html'

class ArchivesView(TemplateView):
    template_name = 'archives.html'

class LeaderboardsView(TemplateView):
    template_name = 'leaderboards.html'

    def get_context_data(self, **kwargs):
        # The players and clans lists produced in this function generally look
        # like this:
        # {
        #    'name': 'someplayer',
        #    OPTIONAL: (indicates this is a player in a clan)
        #    'clan': 'someclan',
        #    'stat': 304, # num of wins, etc.
        #    OPTIONAL: (indicates template should render as a link)
        #    'dumplog': 'https://hardfought.org/blah/blah.html'
        # },

        # TODO: add a cache here.
        # Game.objects.latest('endtime').values('endtime')
        # if this is the same as previously stored endtime (where do we store
        # it? class variable?) then return existing copy of data, otherwise
        # recompute

        # *_stt is the starttime of a game, *_dlg is the dumplog format, and
        # *_nam is the name of the player of the game.
        # These are necessary so that we can generate the dumplog here in the
        # view rather than telling the Game to go look up its Player and Source
        # for extra queries. (The player's name would not be necessary for the
        # player leaderboard, but is necessary for the clan leaderboard.)
        # A possible optimization would be to inject the F(game__player__name)
        # for the Clan query only, and for the Player query just use F(name).
        annotate_kwargs = {
            'firstasc':        F('first_asc__endtime'),
            'firstasc_stt':    F('first_asc__starttime'),
            'firstasc_dlg':    F('first_asc__source__dumplog_fmt'),
            'firstasc_nam':    F('first_asc__player__name'),

            'minturns':        F('lowest_turncount_asc__turns'),
            'minturns_stt':    F('lowest_turncount_asc__starttime'),
            'minturns_dlg':    F('lowest_turncount_asc__source__dumplog_fmt'),
            'minturns_nam':    F('lowest_turncount_asc__player__name'),

            'mintime':         F('fastest_realtime_asc__wallclock'),
            'mintime_stt':     F('fastest_realtime_asc__starttime'),
            'mintime_dlg':     F('fastest_realtime_asc__source__dumplog_fmt'),
            'mintime_nam':     F('fastest_realtime_asc__player__name'),

            # counting with distinct=True is needed here because we aggregate
            # both conducts and achievements - the resulting SQL join produces
            # (#cond x #ach) records per Game under the hood. Counting without
            # distinct will result in that product being the result for both.
            'maxcond':         Count('max_conducts_asc__conducts', distinct=True),
            'maxcond_stt':     F('max_conducts_asc__starttime'),
            'maxcond_dlg':     F('max_conducts_asc__source__dumplog_fmt'),
            'maxcond_nam':     F('max_conducts_asc__player__name'),

            'mostachgame':     Count('max_achieves_game__achievements', distinct=True),
            'mostachgame_stt': F('max_achieves_game__starttime'),
            'mostachgame_dlg': F('max_achieves_game__source__dumplog_fmt'),
            'mostachgame_nam': F('max_achieves_game__player__name'),

            'minscore':        F('min_score_asc__points'),
            'minscore_stt':    F('min_score_asc__starttime'),
            'minscore_dlg':    F('min_score_asc__source__dumplog_fmt'),
            'minscore_nam':    F('min_score_asc__player__name'),

            'maxscore':        F('max_score_game__points'),
            'maxscore_stt':    F('max_score_game__starttime'),
            'maxscore_dlg':    F('max_score_game__source__dumplog_fmt'),
            'maxscore_nam':    F('max_score_game__player__name'),
        }

        # Load basic player/clan data WITHOUT the expensive annotations
        # These fields are stored directly on the model and are fast to query
        basic_fields = ['id', 'name', 'wins', 'total_games', 'unique_deaths', 'unique_ascs',
                       'unique_achievements', 'longest_streak', 'zscore', 'splats',
                       'donations', 'games_over_1000_turns']

        allplayers_basic = list(Player.objects
                                      .filter(total_games__gt=0)
                                      .annotate(clanname=F('clan__name'))
                                      .values(*basic_fields, 'clanname'))
        winplayers_basic = [p for p in allplayers_basic if p['wins'] > 0]

        allclans_basic = list(Clan.objects
                                  .filter(total_games__gt=0)
                                  .values(*basic_fields))
        winclans_basic = [c for c in allclans_basic if c['wins'] > 0]

        # Basic data loaded - these will be used for leaderboards that only need
        # fields stored directly on the model (wins, unique_deaths, etc.)
        allplayers = allplayers_basic
        winplayers = winplayers_basic
        allclans = allclans_basic
        winclans = winclans_basic

        # This function takes one of the four lists above, and formats each
        # dictionary appropriately for consumption by the template.
        def gen_leader_list(base_list, stat, descending):
            list_out = []
            # Leave out entries whose stat is missing or None. That indicates
            # a field was not correctly populated during aggregation, such as
            # a Player who has wins > 0 but first_asc is None; log it, but
            # don't lose the whole leaderboard over one entry. (It also can't
            # be sorted against numbers below.)
            usable = []
            for elem in base_list:
                if stat not in elem or elem[stat] is None:
                    logger.error('malformed query result for leaderboards')
                    logger.error('stat = %s element = %s', stat, str(elem))
                    continue
                usable.append(elem)
            # Note: this sorting will put players with the same amount of wins
            # (or whatever metric stat is) in arbitrary order.
            # The obvious enhancement is to order it by the first player to get
            # there, but that's only straightforward for leaderboard stats that
            # refer directly to a single game (and which don't tend to tie).
            # Other leaderboard stats such as "number of unique achievements" or
            # "donations"? Hard to track.
            # This is not to say it's impossible -- e.g. you could add a
            # "donations_updated" field that gets set to the time the
            # aggregation was run whenever someone's donation count goes up --
            # but it's unclear that anyone actually wants this right now.
            for elem in sorted(usable, key=lambda E: E[stat], reverse=descending):
                # All leaderboards should leave off entries where the stat is 0.
                # Initially this was done on a case by case basis, but there are
                # currently no leaderboards that are capable of showing 0s (some
                # such as most ascensions or most unique asc combos, will never
                # have a 0 because only wins are considered) that we want to
                # show 0s. (Skip rather than stop: on an ascending board a
                # zero would sort first.)
                if elem[stat] == 0:
                    continue

                # elem is either a player or a clan, but this loop doesn't care
                # which
                converted = {
                    'name': elem['name'],
                    'stat': elem[stat],
                }

                # Format datetime fields to ISO format (YYYY-MM-DD HH:MM)
                if stat == 'firstasc' and elem[stat]:
                    converted['stat'] = elem[stat].strftime('%Y-%m-%d %H:%M')

                if 'clanname' in elem and elem['clanname'] is not None:
                    # this is a player, and we want to show the clan
                    converted['clan'] = elem['clanname']
                if (stat + '_stt') in elem:
                    # this is a stat representing a single game, so it has an
                    # associated dumplog
                    converted['dumplog'] = \
                        dumplog_utils.format_dumplog(elem[stat + '_dlg'],
                                                     elem[stat + '_nam'],
                                                     elem[stat + '_stt'])
                list_out.append(converted)
            return list_out

        # The order of these leaderboards determines the order on the page and
        # in the combo box.
        leaderboards = [
            # if stat is absent, then just use id as the stat
            { 'id': 'mostasc', 'stat': 'wins', 'descending': True, 'wins_only': True,
              'title': 'Most Ascensions', 'columntitle': 'Wins' },
            { 'id': 'firstasc', 'descending': False, 'wins_only': True,
              'title': 'Earliest Ascension', 'columntitle': 'Time' },
            { 'id': 'minturns', 'descending': False, 'wins_only': True,
              'title': 'Lowest Turncount Ascension', 'columntitle': 'Turns' },
            { 'id': 'mintime', 'descending': False, 'wins_only': True,
              'title': 'Fastest Realtime Ascension', 'columntitle': 'Wallclock' },
            { 'id': 'maxcond', 'descending': True, 'wins_only': True,
              'title': 'Most Conducts in One Ascension', 'columntitle': 'Conducts' },
            { 'id': 'mostachgame', 'descending': True, 'wins_only': False,
              'title': 'Most Achievements in One Game', 'columntitle': 'Achievements' },
            { 'id': 'mostach', 'descending': True, 'stat': 'unique_achievements',
              'wins_only': False,
              'title': 'Most Achievements Overall', 'columntitle': 'Achievements' },
            { 'id': 'minscore', 'descending': False, 'wins_only': True,
              'title': 'Lowest Scoring Ascension', 'columntitle': 'Points' },
            { 'id': 'maxscore', 'descending': True, 'wins_only': False,
              'title': 'Highest Scoring Game', 'columntitle': 'Points' },
            { 'id': 'longstreak', 'stat': 'longest_streak', 'descending': True,
              'wins_only': True,
              'title': 'Longest Streak', 'columntitle': 'Streak length' },
            { 'id': 'uniquedeaths', 'stat': 'unique_deaths', 'descending': True,
              'wins_only': False,
              'title': 'Most Unique Deaths', 'columntitle': 'Deaths' },
            { 'id': 'uniqueasc', 'stat': 'unique_ascs', 'descending': True,
              'wins_only': True,
              'title': 'Most Unique Ascension Combos', 'columntitle': 'Combos' },
            { 'id': 'zscorerole', 'stat': 'zscore', 'descending': True,
              'wins_only': True,
              'title': 'Highest Z-Score', 'columntitle': 'Z-score' },
            { 'id': 'splats', 'descending': True, 'wins_only': False,
              'title': 'Most Post-Amulet Splats', 'columntitle': 'Splats' },
            { 'id': 'donations', 'descending': True, 'wins_only': False,
              'title': 'Most Successful Swap Chest Donations',
              'columntitle': 'Donations' },
            # removed for 2025 tournament; it's not clear that anyone cares
            # about it, so we'll see if anyone complains
            # { 'id': 'mostgames', 'stat': 'games_over_1000_turns', 'descending': True,
            #   'wins_only': False,
            #   'title': 'Most Games over 1000 Turns', 'columntitle': 'Games' },
        ]
        # Process each leaderboard
        for L in leaderboards:
            stat = L['stat'] if 'stat' in L else L['id']

            # For simple stats (stored on model), use the basic data
            if stat in basic_fields:
                L['players'] = gen_leader_list(winplayers if L['wins_only'] else allplayers,
                                               stat, L['descending'])
                L['clans'] = gen_leader_list(winclans if L['wins_only'] else allclans,
                                             stat, L['descending'])
            else:
                # For complex stats that require JOINs to related Game objects,
                # load only the specific annotations needed for this leaderboard
                if stat == 'firstasc':
                    # Get all players/clans with first ascension
                    top_players = list(Player.objects
                        .filter(first_asc__isnull=False)
                        .annotate(
                            clanname=F('clan__name'),
                            firstasc=F('first_asc__endtime'),
                            firstasc_stt=F('first_asc__starttime'),
                            firstasc_dlg=F('first_asc__source__dumplog_fmt'),
                            firstasc_nam=F('first_asc__player__name')
                        )
                        .order_by('first_asc__endtime')
                        .values('name', 'clanname', 'firstasc', 'firstasc_stt',
                                'firstasc_dlg', 'firstasc_nam'))

                    top_clans = list(Clan.objects
                        .filter(first_asc__isnull=False)
                        .annotate(
                            firstasc=F('first_asc__endtime'),
                            firstasc_stt=F('first_asc__starttime'),
                            firstasc_dlg=F('first_asc__source__dumplog_fmt'),
                            firstasc_nam=F('first_asc__player__name')
                        )
                        .order_by('first_asc__endtime')
                        .values('name', 'firstasc', 'firstasc_stt',
                                'firstasc_dlg', 'firstasc_nam'))

                    L['players'] = gen_leader_list(top_players, stat, L['descending'])
                    L['clans'] = gen_leader_list(top_clans, stat, L['descending'])
                elif stat in ['minturns', 'mintime', 'maxcond', 'mostachgame',
                              'minscore', 'maxscore']:
                    # For other complex leaderboards, annotate only the fields
                    # needed for this specific stat
                    stat_annotations = {k: v for k, v in annotate_kwargs.items()
                                        if k.startswith(stat)}
                    players_annotated = list(Player.objects
                        .filter(total_games__gt=0)
                        .annotate(clanname=F('clan__name'), **stat_annotations)
                        .values('name', 'wins', 'clanname', *stat_annotations.keys()))
                    clans_annotated = list(Clan.objects
                        .filter(total_games__gt=0)
                        .annotate(**stat_annotations)
                        .values('name', 'wins', *stat_annotations.keys()))

                    if L['wins_only']:
                        players_annotated = [p for p in players_annotated
                                             if p.get('wins', 0) > 0]
                        clans_annotated = [c for c in clans_annotated
                                           if c.get('wins', 0) > 0]

                    L['players'] = gen_leader_list(players_annotated, stat, L['descending'])
                    L['clans'] = gen_leader_list(clans_annotated, stat, L['descending'])
        try:
            kwargs['myname'] = get_player(self.request.user).name
        except Player.DoesNotExist:
            # don't do anything if no player found, since you can view
            # leaderboards when not logged in
            pass

        kwargs['leaderboards'] = leaderboards
        return kwargs

class PlayersView(TemplateView):
    template_name = 'players.html'

    def get_context_data(self, **kwargs):
        kwargs['players'] = Player.objects.order_by('-wins', 'name')
        return kwargs

class ClansView(TemplateView):
    template_name = 'clans.html'

    def get_context_data(self, **kwargs):
        # Query for player-clan relationships.
        plr2clan = list(Player.objects.filter(clan__isnull=False)
                        .annotate(clan_name=F('clan__name'))
                        .order_by('name')
                        .values('name','clan_name','clan_admin'))

        # convert:
        # [{'name': 'bob', 'clan_name': 'foo', 'clan_admin': True}, ...]
        #   => { 'foo': [{ 'name': 'bob', 'admin': True}, ...] }
        clan_members = {}
        for plr in plr2clan:
            pname, cname = plr['name'], plr['clan_name']
            if not cname in clan_members:
                # new clan, add it as new list
                clan_members[cname] = []
            clan_members[cname].append({
                'name': pname,
                'admin': plr['clan_admin']
            })

        # All clans list, convert to list to only query db once.
        clanlist = list(Clan.objects.annotate(
            trophy_count=Count('trophies')
        ).order_by('-wins', 'name').values())

        # Now insert the lists of members.
        for clan in clanlist:
            if not clan['name'] in clan_members:
                logger.error('Clan %s exists in db but has no members!', clan['name'])
                continue
            clan['members'] = clan_members[clan['name']]

        # Pass on to template.
        kwargs['clans'] = clanlist
        return kwargs

class SinglePlayerOrClanView(TemplateView):
    template_name = 'singleplayerorclan.html'

    # a "would be nice" feature to have: on the clan page (not the player page),
    # show games that the clan members have in progress. Obviously, not possible
    # to do in the scoreboard alone - it would require the game to do something
    # extra to indicate a game has started, and have that data be accessible
    # even when a game is saved. Probably, the cleanest way to do this would be
    # to have a game write out a file with some basic information when it
    # starts, and wipe that file when it ends, and add the ability for the
    # scoreboard to poll such files.

    def get_context_data(self, **kwargs):
        from tnnt.trophy_grid import generate_combo_grid_data

        if 'clanname' in kwargs:
            kwargs['isClan'] = True
            kwargs['header_key'] = 'clans'
            clan = get_object_or_404(Clan, name=kwargs['clanname'])
            kwargs['player_or_clan'] = clan
            members = Player.objects.filter(clan=clan).order_by('-clan_admin', 'name') \
                            .values('id', 'name','clan_admin')
            kwargs['members'] = members

            # flatten members' names into a list for Game filterings
            member_ids = [ m['id'] for m in members ]

            # for a clan, we want to filter games from any of its members
            base_game_qs = Game.objects.filter(player__in=member_ids)

            # Always show clan trophy tracker to everyone (no login required)
            kwargs['trophy_grid'] = generate_combo_grid_data(clan)

        elif 'playername' in kwargs:
            kwargs['isClan'] = False
            kwargs['header_key'] = 'players'
            player = get_object_or_404(Player, name=kwargs['playername'])
            kwargs['player_or_clan'] = player
            base_game_qs = Game.objects.filter(player=player.id)

            # Generate trophy progress grid for the player
            kwargs['trophy_grid'] = generate_combo_grid_data(player)

        else:
            logger.error('single player/clan view without clan or player name')
            raise ValueError

        # add information to the Game queryset that lets us generate dumplogs,
        # and default sorting
        base_game_qs = base_game_qs.annotate(playername=F('player__name'),
                                             dlg_fmt=F('source__dumplog_fmt')) \
                                   .order_by('-endtime')
        kwargs['ascensions'] = \
            bulk_upd_games(list(base_game_qs.filter(won=True).values()), True)

        # Check if user wants to see all games (default: recent only)
        show_all = self.request.GET.get('show_all', 'false').lower() == 'true'
        kwargs['show_all_games'] = show_all

        if show_all:
            # Show all games (excluding scummed games for performance; see
            # scoreboard.models.SCUMMED_GAME_Q)
            non_scummed_qs = base_game_qs.exclude(SCUMMED_GAME_Q)
            kwargs['recentgames'] = \
                bulk_upd_games(list(non_scummed_qs.values()), False)
        else:
            # 10 most recent games (default behavior)
            kwargs['recentgames'] = \
                bulk_upd_games(list(base_game_qs[:10].values()), False)

        # this only gets the deaths, no other details; we have the ability to
        # get extra details now, but currently there isn't any demand to show
        # additional details in this view.
        kwargs['uniquedeaths'] = sorted(list(uniqdeaths.compile_unique_deaths(base_game_qs)))

        # a little subquerying for achievements...
        gameswith_ach = base_game_qs.filter(achievements__pk=OuterRef('pk'))
        ach_annotate_kwargs = { 'obtained': Exists(gameswith_ach) }
        if kwargs['isClan']:
            ach_annotate_kwargs['has_in_current_game'] = \
                Exists(Player.objects.filter(clan=clan, temp_achievements__pk=OuterRef('pk')))
        else:
            ach_annotate_kwargs['has_in_current_game'] = \
                Exists(player.temp_achievements.filter(pk=OuterRef('pk')))
        achievements = Achievement.objects.annotate(**ach_annotate_kwargs)

        # For clan pages, add info about which members earned each achievement
        if kwargs['isClan']:
            # Pre-fetch all achievement-member relationships in bulk to avoid N+1 queries
            from collections import defaultdict

            # Get all completed achievements for clan members (1 query)
            completed_ach_members = Game.objects.filter(
                player__clan=clan,
                achievements__isnull=False
            ).values('achievements__id', 'player__name', 'player__id').distinct()

            # Get all temp achievements for clan members (1 query)
            temp_ach_members = Player.objects.filter(
                clan=clan,
                temp_achievements__isnull=False
            ).values('temp_achievements__id', 'name', 'id').distinct()

            # Build lookup dictionaries: achievement_id -> set of (player_id, player_name)
            completed_lookup = defaultdict(set)
            for item in completed_ach_members:
                completed_lookup[item['achievements__id']].add(
                    (item['player__id'], item['player__name'])
                )

            temp_lookup = defaultdict(set)
            for item in temp_ach_members:
                temp_lookup[item['temp_achievements__id']].add(
                    (item['id'], item['name'])
                )

            achievements_list = []
            for ach in achievements:
                ach_dict = {
                    'pk': ach.pk,
                    'ingameid': ach.ingameid,
                    'name': ach.name,
                    'description': ach.description,
                    'define': ach.define,
                    'obtained': ach.obtained,
                    'has_in_current_game': ach.has_in_current_game,
                }

                # Get unique members who have this achievement (from pre-fetched data)
                all_members = completed_lookup[ach.pk] | temp_lookup[ach.pk]
                total_members = len(all_members)

                # Sort by player_id descending and take first 12 names
                member_list = [name for pid, name in sorted(all_members, key=lambda x: x[0], reverse=True)[:12]]

                ach_dict['clan_members_count'] = total_members
                ach_dict['clan_members_list'] = member_list
                ach_dict['clan_members_more'] = max(0, total_members - 12)

                achievements_list.append(ach_dict)

            kwargs['achievements'] = achievements_list
        else:
            kwargs['achievements'] = achievements

        # Format streak dates to ISO format (YYYY-MM-DD HH:MM) for display
        # This follows the same pattern as bulk_upd_games for consistency
        if not kwargs['isClan']:
            streaks = player.get_streaks()
            for streak in streaks:
                for game in streak.games:
                    # Store formatted dates as separate attributes to preserve originals
                    game.starttime_formatted = game.starttime.strftime('%Y-%m-%d %H:%M') if game.starttime else ''
                    game.endtime_formatted = game.endtime.strftime('%Y-%m-%d %H:%M') if game.endtime else ''
            kwargs['streaks'] = streaks

        return kwargs

class TrophiesView(TemplateView):
    template_name = 'trophies.html'

    # TODO: Some way of visualizing your progress towards all multi-game-combo
    # trophies: if you do not already have the trophy, display the games that
    # you / your clan has which count towards it, or display all the games
    # necessary and highlight ones that have been done in a different color.
    # Ideally, it would even show ones that have a matching game in progress in
    # a third color.

    def get_context_data(self, **kwargs):
        # only do 3 queries!
        trophies_def = list(Trophy.objects.values('name','description'))
        clan2troph = list(Clan.objects
                              .annotate(field=Value('clans'),
                                        numtroph=Count('trophies__id'))
                              .filter(numtroph__gt=0)
                              .values('name','trophies__name','field'))
        plr2troph = list(Player.objects
                               .annotate(field=Value('players'),
                                         numtroph=Count('trophies__id'))
                               .filter(numtroph__gt=0)
                               .values('name','trophies__name','field'))
        alltroph = clan2troph + plr2troph

        # we need to show all trophies regardless of anyone having them, so
        # first populate the basic structure we need to send to the template
        trophies = {}
        for t in trophies_def:
            trophies[t['name']] = {
                'description' : t['description'],
                'players': [],
                'clans': []
            }

        # lists are [{'name': <player/clan name>,
        #             'trophies__name': 'Both Genders',
        #             'trophies__description': '<desc>',
        #             'field': 'players'}, ...]
        # convert to { 'Both Genders': { 'players': [...],
        #                                'clans': [...],
        #                                'description': '...' },
        #               ...}
        for a in alltroph:
            plr_or_clan_name = a['name']
            tname            = a['trophies__name']
            field            = a['field'] # either "players" or "clans"
            trophies[tname][field].append(plr_or_clan_name)

        # Categorize trophies for better organization
        trophy_categories = [
            {
                'name': 'Race Trophies',
                'trophies': {}
            },
            {
                'name': 'Role Trophies',
                'trophies': {}
            },
            {
                'name': 'Combo Completion Trophies',
                'trophies': {}
            },
            {
                'name': 'Conduct Trophies',
                'trophies': {}
            },
            {
                'name': 'Special Challenge Trophies',
                'trophies': {}
            }
        ]

        # Map trophy names to categories
        for tname, tdata in trophies.items():
            if tname.startswith('Great ') or tname.startswith('Lesser '):
                # Determine if it's a race or role trophy
                if any(race in tname for race in ['Human', 'Dwarf', 'Elf', 'Gnome', 'Orc']):
                    trophy_categories[0]['trophies'][tname] = tdata
                else:
                    trophy_categories[1]['trophies'][tname] = tdata
            elif tname in ['All Roles', 'All Races', 'All Alignments',
                          'Both Genders', 'All Achievements',
                          'NetHack Master', 'NetHack Dominator']:
                trophy_categories[2]['trophies'][tname] = tdata
            elif tname == 'All Conducts':
                trophy_categories[3]['trophies'][tname] = tdata
            elif tname.startswith('Keep ') or tname == 'Never Scum a Game':
                trophy_categories[4]['trophies'][tname] = tdata

        kwargs['trophies'] = trophies
        kwargs['trophy_categories'] = trophy_categories
        return kwargs

class AchievementsView(TemplateView):
    template_name = 'achievements.html'

    def get_context_data(self, **kwargs):
        from collections import defaultdict

        achievements_data = []

        achievements = Achievement.objects.annotate(
            nplayers=Count('game__player', distinct=True),
            nclans=Count('game__player__clan', distinct=True)
        ).order_by('-nplayers', '-nclans', 'id')

        # Pre-fetch all achievement-player relationships in bulk (1 query)
        player_achievements = Player.objects.filter(
            game__achievements__isnull=False
        ).values('game__achievements__id', 'name', 'id').distinct()

        # Pre-fetch all achievement-clan relationships in bulk (1 query)
        clan_achievements = Clan.objects.filter(
            player__game__achievements__isnull=False
        ).values('player__game__achievements__id', 'name', 'id').distinct()

        # Build lookup dictionaries: achievement_id -> list of (entity_id, entity_name)
        players_by_achievement = defaultdict(list)
        for item in player_achievements:
            players_by_achievement[item['game__achievements__id']].append(
                (item['id'], item['name'])
            )

        clans_by_achievement = defaultdict(list)
        for item in clan_achievements:
            clans_by_achievement[item['player__game__achievements__id']].append(
                (item['id'], item['name'])
            )

        for ach in achievements:
            # Get players who earned this achievement (from pre-fetched data)
            players = players_by_achievement[ach.id]
            total_players = len(players)
            # Sort by player_id descending and take first 12 names
            player_list = [name for pid, name in sorted(players, key=lambda x: x[0], reverse=True)[:12]]

            # Get clans who earned this achievement (from pre-fetched data)
            clans = clans_by_achievement[ach.id]
            total_clans = len(clans)
            # Sort by clan_id descending and take first 12 names
            clan_list = [name for cid, name in sorted(clans, key=lambda x: x[0], reverse=True)[:12]]

            achievements_data.append({
                'ingameid': ach.ingameid,
                'name': ach.name,
                'description': ach.description,
                'define': ach.define,
                'nplayers': total_players,
                'nclans': total_clans,
                'player_list': player_list,
                'clan_list': clan_list,
                'players_more': max(0, total_players - 12),
                'clans_more': max(0, total_clans - 12),
            })

        kwargs['achievements'] = achievements_data
        return kwargs

class UniqueDeathsView(TemplateView):
    template_name = 'uniquedeaths.html'

    def get_context_data(self, **kwargs):
        kwargs['deathlist'] = uniqdeaths.get_unique_death_details()
        return kwargs

class AscensionsView(TemplateView):
    template_name = 'ascensions.html'

    def get_context_data(self, **kwargs):
        # Get all ascensions (won games) ordered by newest first
        ascensions_qs = Game.objects.filter(won=True) \
                                    .select_related('player', 'source') \
                                    .values('id', 'player__name', 'role', 'race',
                                           'gender', 'align', 'gender0', 'align0',
                                           'points', 'turns',
                                           'endtime', 'starttime', 'wallclock',
                                           'death',
                                           playername=F('player__name'),
                                           dlg_fmt=F('source__dumplog_fmt')) \
                                    .order_by('-endtime')

        # Use bulk_upd_games to add dumplog URLs, rrga strings, and conducts
        kwargs['ascensions'] = bulk_upd_games(list(ascensions_qs), True)
        return kwargs

class AllGamesView(TemplateView):
    template_name = 'allgames.html'

    def get_context_data(self, **kwargs):
        # Get all legitimate games (exclude scummed) ordered by newest first.
        # See scoreboard.models.SCUMMED_GAME_Q for what "scummed" means.
        games_qs = Game.objects.exclude(SCUMMED_GAME_Q) \
                               .select_related('player', 'source') \
                               .values('id', 'player__name', 'role', 'race',
                                      'gender', 'align', 'gender0', 'align0',
                                      'points', 'turns', 'maxlvl',
                                      'endtime', 'starttime', 'wallclock',
                                      'death', 'won',
                                      playername=F('player__name'),
                                      dlg_fmt=F('source__dumplog_fmt')) \
                               .order_by('-endtime')

        # Use bulk_upd_games to add dumplog URLs and rrga strings
        # For all games view, we don't need conducts (only for ascensions)
        kwargs['games'] = bulk_upd_games(list(games_qs), False)
        return kwargs

class ScummedGamesView(TemplateView):
    template_name = 'scummedgames.html'

    def get_context_data(self, **kwargs):
        # Get all players with their scummed game counts. See
        # scoreboard.models.SCUMMED_GAME_Q for what "scummed" means.
        scummed_criteria = SCUMMED_GAME_Q

        # Get total scummed games for percentage calculation
        total_scummed = Game.objects.filter(scummed_criteria).count()

        # Get total games for percentage calculation
        total_games = Game.objects.count()

        # Calculate percentage of all games that are scummed
        scummed_percentage = (total_scummed / total_games * 100) if total_games > 0 else 0

        # Calculate total real-life time spent scumming
        scummed_time_aggr = Game.objects.filter(scummed_criteria).aggregate(
            Sum('realtime')
        )
        total_scummed_time = scummed_time_aggr['realtime__sum']

        # Get most scummed race/role combination
        scummed_race_role = Game.objects.filter(scummed_criteria).values(
            'race', 'role'
        ).annotate(
            combo_count=Count('*')
        ).order_by('-combo_count').first()

        if scummed_race_role:
            most_scummed_combo = f"{scummed_race_role['race']} {scummed_race_role['role']}"
            most_scummed_count = scummed_race_role['combo_count']
        else:
            most_scummed_combo = None
            most_scummed_count = 0

        # Get player statistics for scummed games
        players_data = Player.objects.annotate(
            scummed_count=Count('game', filter=scummed_q('game__'))
        ).filter(
            scummed_count__gt=0  # Only include players with scummed games
        ).select_related('clan').values(
            'name',
            'clan__name',
            'scummed_count'
        ).order_by('-scummed_count')

        # Calculate percentages and format data
        scummed_list = []
        for player in players_data:
            percentage = (player['scummed_count'] / total_scummed * 100) if total_scummed > 0 else 0
            scummed_list.append({
                'player': player['name'],
                'clan': player['clan__name'] if player['clan__name'] else '',
                'scummed_games': player['scummed_count'],
                'percentage': f"{percentage:.1f}%"
            })

        # Count players with scummed games
        total_players_scummed = len(scummed_list)

        kwargs['scummed_list'] = scummed_list
        kwargs['total_scummed'] = total_scummed
        kwargs['total_games'] = total_games
        kwargs['scummed_percentage'] = scummed_percentage
        kwargs['total_players_scummed'] = total_players_scummed
        kwargs['most_scummed_combo'] = most_scummed_combo
        kwargs['most_scummed_count'] = most_scummed_count
        kwargs['total_scummed_time'] = total_scummed_time
        return kwargs

class ClanMgmtView(View):
    template_name = 'clanmgmt.html'

    def get_context_data(self, **kwargs):

        user = self.request.user
        # we assume the player is already known to exist since both get() and
        # post() check for it
        player = get_player(user)

        kwargs['me'] = player
        kwargs['clan'] = None
        clan = player.clan
        if clan is not None:
            kwargs['clan'] = clan
            kwargs['members'] = Player.objects.filter(clan=clan).order_by('-clan_admin','name')
            # Exclude players who are already members from the invitees list
            kwargs['invitees'] = clan.invitees.exclude(clan=clan).order_by('name')
        kwargs['invites'] = player.invites.all().order_by('name')

        kwargs['clan_freeze'] = self.clan_freeze_in_effect()
        kwargs['clan_freeze_time'] = settings.CLAN_FREEZE_TIME

        if 'invite_member_form' not in kwargs:
            kwargs['invite_member_form'] = InviteMemberForm()
        if 'create_clan_form' not in kwargs:
            kwargs['create_clan_form'] = CreateClanForm()
        if 'set_message_form' not in kwargs:
            kwargs['set_message_form'] = SetMessageForm()

        return kwargs

    def clan_freeze_in_effect(self):
        if settings.CLAN_FREEZE_TIME is None:
            return False  # No freeze if CLAN_FREEZE_TIME is disabled
        return settings.CLAN_FREEZE_TIME <= datetime.now(tz=timezone.utc)

    def get(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return HttpResponseRedirect('/login')

        try:
            get_player(request.user)
        except Player.DoesNotExist:
            return HttpResponse(status=500)

        return render(request, self.template_name, self.get_context_data(**kwargs))

    # FUTURE TODO:
    # This isn't a very Djangoish way of doing things to have a bunch of
    # different post requests to clanmgmt. Ideally they'd all be different
    # endpoints, but not take you to other pages.
    def post(self, request, *args, **kwargs):

        if not request.user.is_authenticated:
            return HttpResponseRedirect('/login')

        # if we passed the auth test above then this shouldn't fail...
        # but it could if the Player db is wiped without the auth.user db being wiped.
        try:
            player = get_player(request.user)
        except Player.DoesNotExist:
            return HttpResponse(status=500)
        ctx = {}

        # People could theoretically mess with POST requests and trigger
        # unexpected behavior. This logic should guard against things like that
        # while logging that it happened so we can see if it's a bug or someone
        # trying to exploit something.
        #
        # How things are logged:
        # error - we actually don't know what to do and the site will have to
        # inform the user a serious error occurred.
        # warning - something happened that the UI is not supposed to allow, but
        # we can handle it gracefully.
        # info - normal events.

        if 'create_clan' in request.POST:
            self.create_clan(request, player, ctx)

        elif 'invite' in request.POST:
            self.invite_to_clan(request, player, ctx)

        elif 'leave' in request.POST:
            self.leave_clan(request, player, ctx)

        elif 'disband' in request.POST:
            self.disband_clan(request, player, ctx)

        elif 'join_clan' in request.POST:
            self.join_clan(request, player, ctx)

        elif 'rescind' in request.POST:
            self.rescind_invite(request, player, ctx)

        elif 'adminify' in request.POST:
            self.make_admin(request, player, ctx)

        elif 'kick' in request.POST:
            self.kick_member(request, player, ctx)

        elif 'set_message' in request.POST:
            self.set_clan_message(request, player, ctx)

        return render(request, self.template_name, self.get_context_data(**ctx))

    # Helper function triggered when a create_clan POST request comes in
    def create_clan(self, request, player, ctx):
        create_clan_form = CreateClanForm(request.POST)

        if not create_clan_form.is_valid():
            ctx['create_clan_form'] = create_clan_form
            return

        new_clan_name = create_clan_form.cleaned_data['clan_name']

        # check if clan operations are allowed
        if not admin_utils.check_clan_operations_allowed(request.user):
            logger.warning('%s attempted clan operation while disabled',
                           player.name)
            ctx['errmsg'] = 'Clan operations are currently disabled by site administrators'
            return

        # clan freeze must not be in effect
        if self.clan_freeze_in_effect():
            logger.warning('%s attempted to make a clan during freeze',
                           player.name)
            ctx['errmsg'] = 'Clans cannot be created with clan freeze in effect'
            return

        # new clan name must be unique
        if Clan.objects.filter(name=new_clan_name).exists():
            ctx['errmsg'] = 'That clan already exists'
            return

        # player must not already be in a clan
        if player.clan is not None:
            logger.warning('%s attempted to make a clan while already in one',
                           player.name)
            ctx['errmsg'] = 'You are already in a clan'
            return

        # if we got here, we're good to create the clan, with the creator as its
        # admin
        newclan = Clan(name=new_clan_name)
        newclan.save()
        player.clan = newclan
        player.clan_admin = True
        player.save()
        logger.info('%s created clan %s', player.name, newclan.name)

    # Helper function triggered when a invite-to-clan POST request comes in
    def invite_to_clan(self, request, player, ctx):
        invite_form = InviteMemberForm(request.POST)

        if not invite_form.is_valid():
            ctx['invite_member_form'] = invite_form
            return

        # check if clan operations are allowed
        if not admin_utils.check_clan_operations_allowed(request.user):
            logger.warning('%s attempted clan operation while disabled',
                           player.name)
            ctx['errmsg'] = 'Clan operations are currently disabled by site administrators'
            return

        # invites are pointless when clan freeze is in effect
        if self.clan_freeze_in_effect():
            ctx['errmsg'] = 'Invites cannot be made with clan freeze in effect'
            return

        # must have a clan to invite to
        if player.clan is None:
            logger.warning('%s attempted to invite without being in a clan',
                           player.name)
            ctx['errmsg'] = "You can't invite people without being in a clan"
            return

        # only clan admins can invite players
        if not player.clan_admin:
            logger.warning('%s attempted to invite without being admin',
                           player.name)
            ctx['errmsg'] = "You can't invite people because you aren't a clan admin"
            return

        # if we got here, we're good to attempt the invite
        invitee_name = invite_form.cleaned_data['invitee']
        try:
            # retrieve player if exists in our database, if not
            # but they are in dgl database, create the player in our
            # database (we need to do this because we need to record
            # them as having an invite)
            invitee = hardfought_utils.find_player(invitee_name)
            invitee.invites.add(player.clan)
            logger.info('%s invited %s to clan %s',
                        player.name, invitee_name, player.clan.name)
        except Player.DoesNotExist:
            logger.warning('%s attempted to invite nonexistent player %s',
                           player.name, invitee_name)
            ctx['errmsg'] = 'No such player exists'
        except sqlite3.Error:
            # find_player couldn't consult the dgamelaunch database (it has
            # logged the details); that's not "no such player"
            ctx['errmsg'] = 'Player lookup is temporarily unavailable, please try again later'

    # Helper function triggered when "leave" is clicked
    def leave_clan(self, request, player, ctx):
        # check if clan operations are allowed
        if not admin_utils.check_clan_operations_allowed(request.user):
            logger.warning('%s attempted clan operation while disabled',
                           player.name)
            ctx['errmsg'] = 'Clan operations are currently disabled by site administrators'
            return

        clan = player.clan

        # must actually have a clan
        if clan is None:
            logger.warning('%s attempted to leave without being in a clan',
                           player.name)
            ctx['errmsg'] = "You're not in a clan to leave"
            return

        # ideally "leave clan" shouldn't be displayed if the player is the only
        # member of their clan, but if the POST is submitted anyway, disband the
        # clan
        if not Player.objects.filter(clan=clan).exclude(id=player.id).exists():
            self.disband_clan(request, player, ctx)
            return

        # don't allow if this would leave the clan admin-less
        if not Player.objects.filter(clan=player.clan, clan_admin=True) \
                             .exclude(id=player.id) \
                             .exists():
            logger.warning('%s attempted to leave and cause admin-less clan',
                           player.name)
            ctx['errmsg'] = 'You cannot leave this clan because it would leave it without an admin'
            return

        # if we got here, we're good to leave the clan
        save_clan_name = player.clan.name
        save_clan = player.clan  # Save reference before clearing
        player.clan = None
        player.save()

        # Invalidate trophy grid cache for both player and clan
        from tnnt.trophy_grid import invalidate_trophy_grid_cache
        invalidate_trophy_grid_cache(player)
        invalidate_trophy_grid_cache(save_clan)

        logger.info('%s left clan %s', player.name, save_clan_name)

    # Helper function triggered when "disband" is clicked
    def disband_clan(self, request, player, ctx):
        # check if clan operations are allowed
        if not admin_utils.check_clan_operations_allowed(request.user):
            logger.warning('%s attempted clan operation while disabled',
                           player.name)
            ctx['errmsg'] = 'Clan operations are currently disabled by site administrators'
            return

        clan = player.clan

        # doesn't make sense if player isn't in a clan
        if clan is None:
            logger.warning('%s attempted to disband with no clan', player.name)
            ctx['errmsg'] = 'You are not in a clan to disband'
            return

        # only admins can disband the clan
        if not player.clan_admin:
            logger.warning('%s attempted to disband as non-admin', player.name)
            ctx['errmsg'] = 'Only clan admins can disband your clan'
            return

        # if we got here, we're good to leave the clan
        clan_members = Player.objects.filter(clan=player.clan)

        # Invalidate trophy grid cache for all members and the clan
        from tnnt.trophy_grid import invalidate_trophy_grid_cache
        invalidate_trophy_grid_cache(clan)
        for member in clan_members:
            invalidate_trophy_grid_cache(member)
            # setting .clan to None is not technically needed because the
            # model has SET_NULL for when the clan is deleted, but why not be
            # explicit?
            member.clan = None
            member.clan_admin = False
            member.save()
        save_clan_name = player.clan.name
        clan.delete()
        logger.info('%s disbanded clan %s',
                    player.name, save_clan_name)

    # Helper function triggered when a clan's invite is clicked
    def join_clan(self, request, player, ctx):
        join_clan_id = request.POST.get('join_clan_id')

        # check if clan operations are allowed
        if not admin_utils.check_clan_operations_allowed(request.user):
            logger.warning('%s attempted clan operation while disabled',
                           player.name)
            ctx['errmsg'] = 'Clan operations are currently disabled by site administrators'
            return

        # joins are not allowed when clan freeze is in effect
        if self.clan_freeze_in_effect():
            logger.warning('%s attempted to join a clan during freeze',
                           player.name)
            ctx['errmsg'] = 'You cannot join a clan with clan freeze in effect'
            return

        # can't join a clan if already in one
        if player.clan:
            logger.warning('%s attempted to join clan %s while already in a clan',
                           player.name, join_clan_id)
            ctx['errmsg'] = "You can't join that clan because you're already in one"
            return

        # clan id actually needs to exist
        # this could theoretically happen normally, where one player loads the
        # clan management page and has an invite for another clan, which has
        # disbanded by the time they submit the join request.
        try:
            newclan = Clan.objects.get(id=join_clan_id)
        except (Clan.DoesNotExist, ValueError, TypeError):
            # ValueError/TypeError guard against a missing or non-numeric
            # join_clan_id in the POST (crafted request), which would otherwise
            # raise before DoesNotExist and 500 the page.
            logger.warning('%s attempted to join nonexistent clan id %s',
                           player.name, join_clan_id)
            ctx['errmsg'] = "You tried to join a clan that doesn't exist"
            return

        # clan needs to have actually extended the invite
        # (this shouldn't come up in normal use)
        if not player.invites.filter(id=join_clan_id):
            logger.warning('%s attempted to join clan %s without an invitation',
                           player.name, newclan.name)
            ctx['errmsg'] = "That clan has not invited you"
            return

        # clan can't be full
        if Player.objects.filter(clan=newclan).count() >= settings.MAX_CLAN_PLAYERS:
            logger.info('%s attempted to join full clan %s',
                        player.name, newclan.name)
            ctx['errmsg'] = "That clan is full"
            return

        # if we got here, we're good to join the clan
        player.clan = newclan
        if player.clan_admin:
            logger.warning('%s, while joining, was somehow already an admin',
                           player.name)
        player.clan_admin = False # to be safe
        player.save()

        # Invalidate trophy grid cache for both player and clan
        from tnnt.trophy_grid import invalidate_trophy_grid_cache
        invalidate_trophy_grid_cache(player)
        invalidate_trophy_grid_cache(newclan)

        # Remove the invite relationship from both sides
        # This is needed so the player doesn't show up in the invitees list
        # after joining the clan
        player.invites.remove(newclan)
        newclan.invitees.remove(player)
        logger.info('%s accepted invite to clan %s',
                    player.name, newclan.name)

    # Helper function for common logic between rescinding, making admin, and
    # kicking - all of these take a player ID and require similar checks to be made.
    # It does NOT check that the other player is in the clan, since invites
    # don't require that.
    # This returns the Player associated with oth_id.
    def clan_admin_other_member_checks(self, request, player, ctx, oth_id, action):
        # other player must exist
        try:
            otherplayer = Player.objects.get(id=oth_id)
        except (Player.DoesNotExist, ValueError, TypeError):
            # ValueError/TypeError guard against a missing or non-numeric id in
            # the POST (crafted request), which would otherwise 500 the page.
            logger.warning('%s attempted to %s with nonexistent id %s',
                           player.name, action, oth_id)
            ctx['errmsg'] = 'The player was not found'
            return None

        # player must be in a clan
        if player.clan is None:
            logger.warning('%s attempted to %s without being in a clan',
                           player.name, action)
            ctx['errmsg'] = "You can't %s if you're not in a clan" % (action)
            return None

        # player must be an admin of their clan
        if not player.clan_admin:
            logger.warning('%s attempted to %s without being an admin',
                           player.name, action)
            ctx['errmsg'] = 'Only admins can %s' % (action)
            return None

        return otherplayer

    # Helper function triggered when "Rescind" is clicked on an invited player
    def rescind_invite(self, request, player, ctx):
        # check if clan operations are allowed
        if not admin_utils.check_clan_operations_allowed(request.user):
            logger.warning('%s attempted clan operation while disabled',
                           player.name)
            ctx['errmsg'] = 'Clan operations are currently disabled by site administrators'
            return

        # post 2021 TODO? all of these helpers should test that the key is in
        # POST, and if not, log an error and return
        rescindee_id = request.POST.get('rescind_id')
        rescindee = self.clan_admin_other_member_checks(request, player, ctx,
                                                        rescindee_id, "rescind")
        if rescindee is None:
            return

        # if we passed checks, we're good to rescind the invite
        rescindee.invites.remove(player.clan)
        logger.info("%s rescinded clan %s's invite to %s",
                    player.name, player.clan.name, rescindee.name)

    # Helper function triggered when "Make Admin" is clicked on a clan member
    def make_admin(self, request, player, ctx):
        # check if clan operations are allowed
        if not admin_utils.check_clan_operations_allowed(request.user):
            logger.warning('%s attempted clan operation while disabled',
                           player.name)
            ctx['errmsg'] = 'Clan operations are currently disabled by site administrators'
            return

        new_admin_id = request.POST.get('kick_or_admin_id')
        new_admin = self.clan_admin_other_member_checks(request, player, ctx,
                                                        new_admin_id, "make admin")
        if new_admin is None:
            return

        # other player must be in this clan
        if player.clan != new_admin.clan:
            logger.warning('%s attempted to make %s (not in their clan) an admin',
                           player.name, new_admin.name)
            ctx['errmsg'] = '%s is not in your clan' % (new_admin.name)
            return

        # can't make someone an admin who's already an admin
        if new_admin.clan_admin:
            logger.warning('%s attempted to make %s an admin, but they already were',
                           player.name, new_admin.name)
            ctx['errmsg'] = '%s is already a clan admin' % (new_admin.name)
            return

        # if we passed checks, we're good to make this person an admin
        new_admin.clan_admin = True
        new_admin.save()
        logger.info('%s made %s an admin of clan %s',
                    player.name, new_admin.name, player.clan.name)

    # Helper function triggered when "Kick" is clicked on a clan member
    def kick_member(self, request, player, ctx):
        # check if clan operations are allowed
        if not admin_utils.check_clan_operations_allowed(request.user):
            logger.warning('%s attempted clan operation while disabled',
                           player.name)
            ctx['errmsg'] = 'Clan operations are currently disabled by site administrators'
            return

        kickee_id = request.POST.get('kick_or_admin_id')
        kickee = self.clan_admin_other_member_checks(request, player, ctx,
                                                     kickee_id, "kick")
        if kickee is None:
            return

        # other player must be in this clan
        if player.clan != kickee.clan:
            logger.warning('%s attempted to kick %s (not in their clan)',
                           player.name, kickee.name)
            ctx['errmsg'] = '%s is not in your clan' % (kickee.name)
            return

        if kickee.id == player.id:
            # the UI should not allow this, but "kick self out" is basically the
            # same as leaving... (compare resolved ints; kickee_id is a POST
            # string, so comparing it to player.id directly never matched and
            # let an admin kick themselves, bypassing leave_clan's admin-less
            # guard and orphaning the clan)
            logger.warning('%s is kicking themself out of their clan, not leaving',
                           player.name)
            self.leave_clan(request, player, ctx)
            return

        # if we passed checks, we're good to kick this player out of the clan
        save_clan = kickee.clan  # Save reference before clearing
        kickee.clan = None
        kickee.clan_admin = False
        kickee.save()

        # Invalidate trophy grid cache for both kicked player and clan
        from tnnt.trophy_grid import invalidate_trophy_grid_cache
        invalidate_trophy_grid_cache(kickee)
        invalidate_trophy_grid_cache(save_clan)

        logger.info('%s kicked %s out of clan %s',
                    player.name, kickee.name, save_clan.name)
        # FUTURE TODO: would be nice if this and all the other post operations
        # also updated a context message that gets displayed to show success; in
        # this case it would be "Successfully kicked foo out of the clan"

    def set_clan_message(self, request, player, ctx):
        if player.clan is None:
            logger.warning("%s is not in a clan but attempted to set a message",
                           player.name)
            ctx['errmsg'] = "You can't set a clan message - you're not in a clan"
            return

        if not player.clan_admin:
            logger.warning("%s is not a clan admin but attempted to set a message",
                           player.name)
            ctx['errmsg'] = "You can't set a clan message - you aren't an admin"
            return

        set_msg_form = SetMessageForm(request.POST)

        if not set_msg_form.is_valid():
            ctx['set_message_form'] = set_msg_form
            return

        clan = player.clan
        clan.message = set_msg_form.cleaned_data['message']
        clan.save()
        logger.info('%s set the message of clan %s to "%s"',
                    player.name, clan.name, clan.message)

    # FUTURE TODO: functionality for a clanless player to request becoming a
    # member of a clan they input, admins can accept (inverse of invites)
    # FUTURE TODO: functionality for a clanless player to raise a flag saying
    # "looking for a clan!" and all such players are listed either publicly or
    # to clan admins (probably publicly)
    # FUTURE TODO: decline an invite

@method_decorator(
    ratelimit_exclude_localhost(key='ip', rate='100/m', method='GET'),
    name='get'
)
class TrophyGridGamesView(View):
    """
    API endpoint to fetch games for a specific role-race-alignment combo.
    Used by clickable trophy grid cells. Rate limited like the rest of /api/.
    """
    def get(self, request):
        from django.http import JsonResponse

        # Get parameters
        entity_type = request.GET.get('entity_type')  # 'player' or 'clan'
        entity_id = request.GET.get('entity_id')
        role = request.GET.get('role')
        race = request.GET.get('race')
        align = request.GET.get('align')

        # Validate parameters
        if not all([entity_type, entity_id, role, race, align]):
            return JsonResponse({
                'error': 'Missing required parameters'
            }, status=400)

        if entity_type not in ['player', 'clan']:
            return JsonResponse({
                'error': 'Invalid entity_type'
            }, status=400)

        # Get base queryset based on entity type
        try:
            if entity_type == 'player':
                player = Player.objects.get(id=entity_id)
                base_qs = Game.objects.filter(player=player)
            else:  # clan
                clan = Clan.objects.get(id=entity_id)
                member_ids = Player.objects.filter(
                    clan=clan
                ).values_list('id', flat=True)
                base_qs = Game.objects.filter(player__in=member_ids)
        except (Player.DoesNotExist, Clan.DoesNotExist, ValueError, TypeError):
            # ValueError/TypeError: entity_id isn't a number (crafted URL)
            return JsonResponse({
                'error': 'Entity not found'
            }, status=404)

        # Filter by combo
        combo_qs = base_qs.filter(
            role=role,
            race=race,
            align0=align
        )

        # Get mines+soko games
        mines_soko_games = combo_qs.filter(
            mines_soko=True
        ).select_related('player', 'source').values(
            'id', 'player__name', 'endtime', 'points',
            'turns', 'gender0', 'starttime', 'role', 'race', 'align0',
            playername=F('player__name'),
            dlg_fmt=F('source__dumplog_fmt')
        ).order_by('-endtime')[:20]  # Limit to 20 most recent

        # Get ascensions (male and female)
        ascension_games = combo_qs.filter(
            won=True
        ).select_related('player', 'source').values(
            'id', 'player__name', 'endtime', 'points',
            'turns', 'gender0', 'starttime', 'role', 'race', 'align0',
            playername=F('player__name'),
            dlg_fmt=F('source__dumplog_fmt')
        ).order_by('-endtime')[:20]  # Limit to 20 most recent

        # Format games using bulk_upd_games
        mines_soko_list = bulk_upd_games(list(mines_soko_games), False)
        ascension_list = bulk_upd_games(list(ascension_games), False)

        # Separate ascensions by gender
        male_ascs = [g for g in ascension_list if g.get('gender0') == 'Mal']
        female_ascs = [g for g in ascension_list if g.get('gender0') == 'Fem']

        return JsonResponse({
            'combo': {
                'role': role,
                'race': race,
                'align': align
            },
            'games': {
                'mines_soko': mines_soko_list,
                'male_ascensions': male_ascs,
                'female_ascensions': female_ascs
            }
        })

class ArchiveFileView(View):
    """
    Serves static HTML files from tournament archives (2018-2024).
    Files are served from staticfiles/archives/<year>/ at URL /archives/<year>/
    """
    def get(self, request, year, path='index.html'):
        import os
        from django.http import FileResponse, Http404
        from django.conf import settings

        # Archives are per-year directories (2018-...). Constrain year to four
        # digits so it can't be '..' or otherwise escape the archives root.
        if not re.fullmatch(r'\d{4}', year):
            raise Http404("Invalid archive year")

        # Construct the file path
        if not path:
            path = 'index.html'

        file_path = os.path.join(
            settings.STATIC_ROOT,
            'archives',
            year,
            path
        )

        # Security check: ensure the path is within the archives directory.
        # Compare with a trailing separator so a sibling dir sharing the year
        # as a prefix can't satisfy a bare startswith().
        archive_base = os.path.join(settings.STATIC_ROOT, 'archives', year)
        real_path = os.path.realpath(file_path)
        real_base = os.path.realpath(archive_base)

        if real_path != real_base and \
                not real_path.startswith(real_base + os.sep):
            raise Http404("Invalid archive path")

        # Serve the file (not directories)
        if os.path.isdir(file_path):
            raise Http404("Archive file not found")

        try:
            return FileResponse(
                open(file_path, 'rb'),
                content_type=self._get_content_type(file_path)
            )
        except FileNotFoundError:
            raise Http404("Archive file not found")

    def _get_content_type(self, file_path):
        """Determine content type based on file extension or content"""
        import mimetypes
        import os

        # Try to guess from extension first
        content_type, _ = mimetypes.guess_type(file_path)

        if content_type:
            return content_type

        # For files without extensions, check if it's HTML
        # (2021-2024 archives have extension-less HTML files)
        try:
            with open(file_path, 'rb') as f:
                first_bytes = f.read(512).lower()
                if b'<!doctype html' in first_bytes or b'<html' in first_bytes:
                    return 'text/html'
        except:
            pass

        # Default fallback
        return 'application/octet-stream'

class AdminPanelView(View):
    """
    Admin panel for site administrators.
    Allows toggling non-admin logins and clan operations.
    """
    template_name = 'adminpanel.html'

    def get(self, request, *args, **kwargs):
        # Check if user is authenticated and is an admin
        if not request.user.is_authenticated:
            return HttpResponseRedirect('/login?next=/admin-panel')

        if not admin_utils.is_admin(request.user):
            return HttpResponse(
                'Access denied. You must be a site administrator.',
                status=403
            )

        # Get current site settings
        site_settings = admin_utils.get_site_settings()

        # Check if manual refresh was requested
        refresh = request.GET.get('refresh', False)

        # Cache keys
        cache_key_multi = 'admin_panel_multi_accounts'
        cache_key_scummers = 'admin_panel_scummers'
        cache_timeout = 300  # 5 minutes

        # Get multi-account detection data (cached or fresh)
        if refresh:
            cache.delete(cache_key_multi)
            multi_accounts = None
        else:
            multi_accounts = cache.get(cache_key_multi)

        if multi_accounts is None:
            logger.info('Cache miss for multi_accounts, querying all servers...')
            multi_accounts = hardfought_utils.get_multi_account_ips()
            cache.set(cache_key_multi, multi_accounts, cache_timeout)
            logger.info('Cached multi_accounts data for %d seconds', cache_timeout)
        else:
            logger.info('Cache hit for multi_accounts')

        # Get excessive scumming data (cached or fresh)
        if refresh:
            cache.delete(cache_key_scummers)
            scummers_list = None
        else:
            scummers_list = cache.get(cache_key_scummers)

        if scummers_list is None:
            logger.info('Cache miss for scummers, querying database...')
            scummers = Player.objects.filter(games_scummed__gte=100) \
                .select_related('clan') \
                .order_by('-games_scummed')

            # Add IP, warning level, and scum rate to each scummer
            scummers_list = []
            for player in scummers:
                player.last_ip = (
                    hardfought_utils.get_player_last_ip(player.name)
                )
                player.warning_level = (
                    'serious' if player.games_scummed >= 500 else 'warning'
                )

                # Calculate peak games per second (max burst rate)
                # Group scummed games by second and find the maximum
                peak_burst = Game.objects.filter(
                    SCUMMED_GAME_Q, player=player
                ).annotate(
                    second=TruncSecond('starttime')
                ).values('second').annotate(
                    count=Count('id')
                ).order_by('-count').first()

                if peak_burst:
                    player.peak_scum_rate = peak_burst['count']
                else:
                    player.peak_scum_rate = None

                scummers_list.append(player)

            cache.set(cache_key_scummers, scummers_list, cache_timeout)
            logger.info('Cached scummers data for %d seconds', cache_timeout)
        else:
            logger.info('Cache hit for scummers')

        context = {
            'site_settings': site_settings,
            'is_admin': True,
            'multi_accounts': multi_accounts,
            'scummers': scummers_list,
            'cache_refreshed': refresh,
        }

        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        # Check if user is authenticated and is an admin
        if not request.user.is_authenticated:
            return HttpResponseRedirect('/login?next=/admin-panel')

        if not admin_utils.is_admin(request.user):
            return HttpResponse(
                'Access denied. You must be a site administrator.',
                status=403
            )

        # Get current site settings
        site_settings = admin_utils.get_site_settings()

        # Handle toggle actions
        if 'toggle_logins' in request.POST:
            site_settings.login_enabled = not site_settings.login_enabled
            site_settings.updated_by = request.user.username
            site_settings.save()
            logger.info(
                '%s %s non-admin logins',
                request.user.username,
                'enabled' if site_settings.login_enabled else 'disabled'
            )

        elif 'toggle_clan_operations' in request.POST:
            site_settings.clan_operations_enabled = \
                not site_settings.clan_operations_enabled
            site_settings.updated_by = request.user.username
            site_settings.save()
            logger.info(
                '%s %s clan operations',
                request.user.username,
                'enabled' if site_settings.clan_operations_enabled else 'disabled'
            )

        # Redirect back to GET to prevent form resubmission
        return HttpResponseRedirect('/admin-panel')

class LoginsDisabledView(TemplateView):
    """
    Page shown when non-admin logins are disabled
    """
    template_name = 'logins_disabled.html'

class TnntLoginView(LoginView):
    """
    Standard Django login view, except that while non-admin logins are
    disabled, login attempts by non-admins redirect straight to the
    logins disabled page without being authenticated. Authenticating
    them would create User/Player records as a side effect, making
    blocked players show up on the players page.
    """
    def post(self, request, *args, **kwargs):
        if not admin_utils.get_site_settings().login_enabled:
            username = request.POST.get('username', '')
            if username not in settings.SITE_ADMINS:
                logger.info(
                    'Blocked login attempt by %s: non-admin logins disabled',
                    username
                )
                return HttpResponseRedirect('/logins-disabled')
        return super().post(request, *args, **kwargs)
