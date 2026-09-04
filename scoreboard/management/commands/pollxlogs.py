from django.core.management.base import BaseCommand, CommandError
from scoreboard.models import Source, Game, Player, Conduct, Achievement
from django.db import transaction
from scoreboard.parsers import parse_xlog_line
from tnnt import settings
from tnnt import uniqdeaths
from pathlib import Path
import requests
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger() # root logger

# xlogfile fields that have the same name in the Game model.
SIMPLE_XLOG_FIELDS = ['version', 'role', 'race', 'gender', 'align', 'points',
                      'turns', 'maxlvl', 'death', 'align0', 'gender0',
                      'deathlev']

# Every xlog field game_from_xlog() reads directly. A record missing any of
# them is malformed and is skipped with a log message instead of crashing the
# whole import with a KeyError.
REQUIRED_XLOG_FIELDS = frozenset(SIMPLE_XLOG_FIELDS + [
    'name', 'flags', 'achieve', 'conduct', 'starttime', 'endtime', 'realtime'
])

# Outcomes of importing one xlog record; game_from_xlog() returns one of the
# first three, import_from_file() counts all four.
ADDED = 'added'
FILTERED = 'filtered'
DUPLICATE = 'duplicate'
BAD = 'bad'

# Download settings for xlogfile syncing: (connect, per-read) timeout in
# seconds, and how much to write at a time.
SYNC_TIMEOUT = (10, 60)
SYNC_CHUNK_SIZE = 64 * 1024

class xlog_flags:
    WIZARD  = 0x1
    EXPLORE = 0x2
    NOBONES = 0x4

def game_from_xlog(source, xlog_dict, auto_detect_source=False,
                   conducts_cache=None, achievements_cache=None):
    '''
    Create and save a Game from a dictionary of fields that comes from the
    xlog. This function contains the custom "business logic" of converting
    fields that are stored differently in Game than in the xlogfile, and
    also mapping to Player.

    Return ADDED if a Game was created, FILTERED if the record was
    deliberately not imported (wizard/explore mode, outside the tournament
    window), or DUPLICATE if this game is already in the database.

    Raise ValueError if the record is missing a required field. Any other
    exception (including database errors) propagates too; the caller runs
    this inside a savepoint and skips the record.

    `source` is a Source object that the resulting Game will be associated
    with.
    `auto_detect_source` if True, will try to detect the source from the
    xlog's server field when using --file option.
    `conducts_cache` if provided, should be a list of all Conduct objects
    (avoids repeated queries)
    `achievements_cache` if provided, should be a list of all Achievement
    objects (avoids repeated queries)

    SIDE EFFECT: This searches for a player of the given name, and if they
    cannot be found, it will create that Player. (This is one of the two
    ways Players are naturally created.)
    '''
    missing = REQUIRED_XLOG_FIELDS.difference(xlog_dict)
    if missing:
        raise ValueError('xlog record is missing field(s): %s'
                         % ', '.join(sorted(missing)))

    # Auto-detect source from xlog server field if requested
    if auto_detect_source and 'server' in xlog_dict:
        server_mapping = {
            'us.hardfought.org': 'hdf',
            'www.hardfought.org': 'hdf',
            'hardfought.org': 'hdf',
            'eu.hardfought.org': 'hfe',
            'au.hardfought.org': 'hfa',
        }

        server_value = xlog_dict['server']
        if server_value in server_mapping:
            try:
                source = Source.objects.get(server=server_mapping[server_value])
                logger.debug('Auto-detected source: %s from server=%s',
                             source.server, server_value)
            except Source.DoesNotExist:
                logger.warning('Could not find Source for server=%s, using default',
                               server_value)

    kwargs = {'source': source}

    # filter explore/wizmode games
    if xlog_dict['flags'] & xlog_flags.WIZARD:
        logger.info('Game not parsed because it was in wizard mode')
        return FILTERED
    if xlog_dict['flags'] & xlog_flags.EXPLORE:
        logger.info('Game not parsed because it was in explore mode')
        return FILTERED

    # time/duration information
    # while doing this, also filter games that partially or completely fall
    # outside the time window of the tournament
    kwargs['starttime'] = datetime.fromtimestamp(xlog_dict['starttime'], timezone.utc)
    kwargs['endtime'] = datetime.fromtimestamp(xlog_dict['endtime'], timezone.utc)
    if kwargs['starttime'] < settings.TOURNAMENT_START:
        logger.info('Game not parsed because it started before tournament start: %s'
                    % (str(kwargs['starttime'])))
        return FILTERED
    if kwargs['endtime'] > settings.TOURNAMENT_END:
        logger.info('Game not parsed because it ended after tournament end: %s'
                    % (str(kwargs['endtime'])))
        return FILTERED
    kwargs['realtime'] = timedelta(seconds=xlog_dict['realtime'])
    kwargs['wallclock'] = kwargs['endtime'] - kwargs['starttime']

    # Skip records that are already in the database. dgamelaunch only allows
    # one game per user per server at a time, so (player, starttime, source)
    # identifies a game; a duplicate can only mean this xlog line has been
    # read before (e.g. a Source's file position was reset). This is checked
    # by name, before the Player row is looked up or created, so that a
    # duplicate line for a player not yet in the database leaves nothing
    # behind.
    if Game.objects.filter(player__name=xlog_dict['name'],
                           starttime=kwargs['starttime'],
                           source=source).exists():
        logger.info('Skipping duplicate game: %s on %s, started %s',
                    xlog_dict['name'], source.server, kwargs['starttime'])
        return DUPLICATE

    # simple fields get keyed directly to keyword args to Game.objects.create()
    for key in SIMPLE_XLOG_FIELDS:
        kwargs[key] = xlog_dict[key]

    # Normalize the death string for efficient unique death queries
    # Skip normalization if the death should be rejected
    if not uniqdeaths.reject(kwargs['death']):
        kwargs['normalized_death'] = uniqdeaths.normalize(kwargs['death'])
    else:
        kwargs['normalized_death'] = None

    # assign 'won' boolean
    if xlog_dict['achieve'] & 0x100:
        kwargs['won'] = True
    else:
        # a non-winning game is a splat if they had the amulet at some point
        # (we count escapes in celestial disgrace and any other
        # non-ascension end to the game as a splat)
        if xlog_dict['achieve'] & 0x20:
            kwargs['splatted'] = True

    # ditto for mines/soko (requires both)
    if (xlog_dict['achieve'] & 0x600) == 0x600:
        kwargs['mines_soko'] = True

    # find/create player
    try:
        player = Player.objects.get(name=xlog_dict['name'])
    except Player.DoesNotExist:
        player = Player(name=xlog_dict['name'], clan=None, clan_admin=False)
        player.save()
    kwargs['player'] = player

    game = Game.objects.create(**kwargs)

    # Use cached conducts/achievements if provided, otherwise query
    conducts_to_check = conducts_cache if conducts_cache is not None else Conduct.objects.all()
    achievements_to_check = achievements_cache if achievements_cache is not None else Achievement.objects.all()

    # Collect matching conducts and achievements, then add in bulk
    matching_conducts = []
    for conduct in conducts_to_check:
        if conduct.xlogfield in xlog_dict and xlog_dict[conduct.xlogfield] & (1 << conduct.bit):
            matching_conducts.append(conduct)

    matching_achievements = []
    for achieve in achievements_to_check:
        if achieve.xlogfield in xlog_dict and xlog_dict[achieve.xlogfield] & (1 << achieve.bit):
            matching_achievements.append(achieve)

    # Bulk add to reduce transactions. (create() already saved the Game;
    # M2M adds don't need another save.)
    if matching_conducts:
        game.conducts.add(*matching_conducts)
    if matching_achievements:
        game.achievements.add(*matching_achievements)

    return ADDED

def import_from_file(path, src):
    '''
    Turn xlog records from the xlogfile at `path` into Game objects.

    If `src` is a Source, start reading at src.file_pos, process only
    complete (newline-terminated) lines, and advance src.file_pos to the
    end of the last complete line. A partial trailing line (the file was
    fetched while the server was still writing that record) is left for the
    next poll to complete; importing it now would create a Game with
    missing fields and turn the rest of the record into a garbage line.
    If `src` is None (the --file option), the whole file is read, a missing
    final newline is tolerated, and the source is auto-detected from each
    record's server field.

    Each record is imported inside its own savepoint, so a malformed line
    or a database error affects only that record: it is logged and
    skipped, and the rest of the file is still imported. The whole call is
    one transaction, so the file position only advances if the import
    completes.

    Return a dict of counters keyed by ADDED, FILTERED, DUPLICATE and BAD.
    '''
    logger.info('Importing Games from local file %s', path)
    auto_detect = False
    if src is None:
        # When using --file option, we'll auto-detect the source from each xlog entry
        local_src = Source.objects.all()[0]  # Default fallback
        auto_detect = True
        start_pos = 0
        logger.info('Auto-detection mode enabled for source selection')
    else:
        local_src = src
        start_pos = src.file_pos

    # Pre-load conducts and achievements once to avoid repeated queries
    conducts_cache = list(Conduct.objects.all())
    achievements_cache = list(Achievement.objects.all())
    logger.debug('Cached %d conducts and %d achievements',
                 len(conducts_cache), len(achievements_cache))

    # Binary mode, so that file positions are byte offsets and match the
    # byte ranges sync_local_file() requests.
    with Path(path).open('rb') as xlog_file:
        xlog_file.seek(start_pos)
        data = xlog_file.read()

    lines = data.split(b'\n')
    # What follows the last newline is either empty (the file ended with a
    # newline) or an unterminated partial line.
    remainder = lines.pop()
    consumed = len(data) - len(remainder)
    if remainder and src is None:
        # a complete file that just lacks a trailing newline
        lines.append(remainder)
        consumed = len(data)
    elif remainder:
        logger.info('Leaving %d bytes of a partial trailing line in %s for '
                    'the next poll', len(remainder), path)

    counts = {ADDED: 0, FILTERED: 0, DUPLICATE: 0, BAD: 0}
    offset = start_pos
    with transaction.atomic():
        for raw_line in lines:
            line_offset = offset
            offset += len(raw_line) + 1
            raw_line = raw_line.rstrip(b'\r')
            if not raw_line.strip():
                continue
            line = raw_line.decode('utf-8', errors='replace')
            try:
                xlog_entry = parse_xlog_line(line)
            except ValueError as e:
                counts[BAD] += 1
                logger.error('Skipping unparseable xlog line at byte %d of '
                             '%s: %s: %r', line_offset, path, e, line[:200])
                continue
            try:
                # Savepoint: a failure in here rolls back only this record
                # (including a Player row created for it) and leaves the
                # surrounding transaction usable.
                with transaction.atomic():
                    result = game_from_xlog(
                        local_src, xlog_entry,
                        auto_detect_source=auto_detect,
                        conducts_cache=conducts_cache,
                        achievements_cache=achievements_cache)
            except Exception:
                counts[BAD] += 1
                logger.exception('Skipping xlog line at byte %d of %s '
                                 '(import failed): %r',
                                 line_offset, path, line[:200])
                continue
            counts[result] += 1

        if src is not None:
            src.file_pos = start_pos + consumed
            src.save()

    logger.info('%s: %d games added, %d filtered, %d duplicates, '
                '%d bad lines skipped', path, counts[ADDED],
                counts[FILTERED], counts[DUPLICATE], counts[BAD])
    return counts

def import_records(src):
    xlog_path = Path(settings.XLOG_DIR) / src.local_file
    return import_from_file(xlog_path, src)

def content_range_start(response):
    # Return the first byte position from a 206 response's Content-Range
    # header ("bytes 1234-5678/9999"), or None if it is absent/malformed.
    value = response.headers.get('Content-Range', '')
    if not value.startswith('bytes '):
        return None
    try:
        return int(value[len('bytes '):].split('-', 1)[0])
    except ValueError:
        return None

def content_range_total(response):
    # Return the total length from a 416 response's Content-Range header
    # ("bytes */9999"), or None if it is absent/malformed.
    value = response.headers.get('Content-Range', '')
    if not value.startswith('bytes */'):
        return None
    try:
        return int(value[len('bytes */'):])
    except ValueError:
        return None

def sync_local_file(url, local_file):
    '''
    Append any new bytes of the remote xlogfile at `url` to the local copy.
    Uses an HTTP Range request from the local file's current length, so only
    new games are transferred.

    Return True if the local copy is up to date (including "nothing new"),
    False if the download failed and the local copy may be behind. Nothing
    is ever written unless the server is sending exactly the bytes that
    follow the local copy: a 206 whose Content-Range starts at our offset,
    or the whole file when our copy is empty.
    '''
    logger.info('Syncing remote xlog file from %s', url)
    xlog_path = Path(settings.XLOG_DIR) / local_file
    with xlog_path.open('ab') as xlog_file:
        offset = xlog_file.tell()
        try:
            r = requests.get(url, headers={
                'Range': 'bytes=%d-' % offset,
                # a gzip-compressed partial body cannot be decoded
                'Accept-Encoding': 'identity',
            }, stream=True, timeout=SYNC_TIMEOUT)
        except requests.RequestException as e:
            logger.error('Could not fetch %s: %s', url, e)
            return False
        with r:
            if r.status_code == 416:
                # Range not satisfiable: the remote file is not longer than
                # our copy. Between polls with no new games that's the
                # normal answer; a remote file that is *shorter* than our
                # copy has been truncated or rotated and needs a look.
                total = content_range_total(r)
                if total is not None and total < offset:
                    logger.warning('Remote %s is %d bytes but local copy '
                                   '%s is %d bytes: truncated or rotated?',
                                   url, total, xlog_path, offset)
                else:
                    logger.info('No new data at %s', url)
                return True
            if r.status_code == 200 and offset == 0:
                # The server ignored the Range header and sent the whole
                # file, which from an empty local copy is exactly what we
                # asked for. Apache does this for an empty file (no 206, no
                # 416), which is how every poll looks until the first game
                # of the tournament is logged.
                logger.info('%s sent as a whole file (local copy empty)',
                            url)
            elif r.status_code != 206:
                # Otherwise only 206 means the server honoured the Range
                # request. A 200 here would be the whole file from byte 0,
                # and appending it would duplicate every game in it.
                logger.warning('Not syncing %s: expected 206 Partial '
                               'Content, got %d', url, r.status_code)
                return False
            elif content_range_start(r) != offset:
                logger.error('Not syncing %s: Content-Range %r does not '
                             'start at the requested offset %d', url,
                             r.headers.get('Content-Range'), offset)
                return False
            try:
                for chunk in r.iter_content(chunk_size=SYNC_CHUNK_SIZE):
                    xlog_file.write(chunk)
            except requests.RequestException as e:
                # Whatever was written is a valid prefix of the remote
                # file; the next poll resumes from the new local length.
                logger.error('Download of %s interrupted: %s', url, e)
                return False
    return True

class Command(BaseCommand):
    help = "Poll Sources (xlogfiles) for new game data"

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            help='Load games from this xlog file instead of using sources in the database'
        )

    def handle(self, *args, **options):
        sources = Source.objects.all()
        if len(sources) == 0:
            raise CommandError('There are no sources in the database to poll!')
        if options.get('file') is not None:
            import_from_file(options['file'], None)
            return

        # Each source is synced and imported independently: a server that
        # is down, or a broken line in one xlogfile, must not stop the other
        # servers' games from being processed.
        failed = []
        for src in sources:
            try:
                if not sync_local_file(src.location, src.local_file):
                    failed.append('%s sync' % src.server)
            except Exception:
                logger.exception('Syncing source %s failed', src.server)
                failed.append('%s sync' % src.server)
            # import whatever is on disk, even if the sync just failed
            try:
                import_records(src)
            except Exception:
                logger.exception('Importing source %s failed', src.server)
                failed.append('%s import' % src.server)
        if failed:
            # non-zero exit so the cron wrapper records the failure
            raise CommandError('pollxlogs finished with failures: %s'
                               % ', '.join(failed))
