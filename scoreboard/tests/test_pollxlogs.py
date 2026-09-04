import tempfile
from pathlib import Path
from unittest import mock

import requests
from django.core.management.base import CommandError
from django.test import TestCase

import tnnt.settings
from scoreboard.management.commands import pollxlogs
from scoreboard.management.commands.pollxlogs import (
    ADDED, BAD, DUPLICATE, FILTERED, import_from_file, sync_local_file,
)
from scoreboard.models import Game, Player, Source
from scoreboard.tests.helpers import in_window, xlog_line


class ImportFromFileTests(TestCase):
    fixtures = ['conducts', 'achievements', 'sources']

    def setUp(self):
        self.src = Source.objects.get(server='hdf')
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'hdf.tnnt.xlog'

    def write(self, text, mode='w'):
        with open(self.path, mode) as f:
            f.write(text)

    def test_value_containing_equals_sign_imports(self):
        self.write(xlog_line(death='killed by a kitten called a=b'))
        counts = import_from_file(self.path, self.src)
        self.assertEqual(counts[ADDED], 1)
        self.assertEqual(Game.objects.get().death,
                         'killed by a kitten called a=b')

    def test_conducts_and_achievements_are_attached(self):
        # conduct bit 0 and tnntachieve0 bit 0 are whatever the fixtures say
        # they are; just check that set bits produce M2M rows.
        self.write(xlog_line(conduct='0x1', tnntachieve0='0x1'))
        import_from_file(self.path, self.src)
        game = Game.objects.get()
        self.assertEqual(game.conducts.count(), 1)
        self.assertEqual(game.achievements.count(), 1)
        self.assertEqual(game.conducts.get().bit, 0)

    def test_bad_lines_are_skipped_and_rest_imported(self):
        text = (xlog_line(name='alice')
                + '\n'
                + 'garbage without an equals sign\n'
                + xlog_line(name='bob', flags=None)   # required field gone
                + xlog_line(name='carol', start=in_window(5)))
        self.write(text)
        with self.assertLogs(level='ERROR') as logs:
            counts = import_from_file(self.path, self.src)
        self.assertEqual(counts[ADDED], 2)
        self.assertEqual(counts[BAD], 2)
        self.assertEqual(set(Player.objects.values_list('name', flat=True)),
                         {'alice', 'carol'})
        # both bad lines were reported, with the offending text
        self.assertTrue(any('garbage without' in m for m in logs.output))
        self.assertTrue(any('missing field(s): flags' in m
                            for m in logs.output))
        # the whole batch was consumed
        self.src.refresh_from_db()
        self.assertEqual(self.src.file_pos, len(text.encode()))

    def test_partial_trailing_line_waits_for_next_poll(self):
        full = xlog_line(name='alice')
        partial = xlog_line(name='bob', start=in_window(5))
        cut = len(partial) // 2
        self.write(full + partial[:cut])

        counts = import_from_file(self.path, self.src)
        self.assertEqual(counts[ADDED], 1)
        self.assertEqual(counts[BAD], 0)
        self.src.refresh_from_db()
        self.assertEqual(self.src.file_pos, len(full.encode()))
        self.assertFalse(Player.objects.filter(name='bob').exists())

        # the rest of the record arrives with the next sync
        self.write(partial[cut:], mode='a')
        counts = import_from_file(self.path, self.src)
        self.assertEqual(counts[ADDED], 1)
        self.assertEqual(Game.objects.count(), 2)
        self.src.refresh_from_db()
        self.assertEqual(self.src.file_pos, len((full + partial).encode()))

    def test_duplicate_line_is_skipped(self):
        line = xlog_line()
        self.write(line + line)
        counts = import_from_file(self.path, self.src)
        self.assertEqual(counts[ADDED], 1)
        self.assertEqual(counts[DUPLICATE], 1)
        self.assertEqual(Game.objects.count(), 1)

        # re-reading the file from the start (e.g. after a file_pos reset)
        # adds nothing either
        self.src.file_pos = 0
        counts = import_from_file(self.path, self.src)
        self.assertEqual(counts[ADDED], 0)
        self.assertEqual(counts[DUPLICATE], 2)
        self.assertEqual(Game.objects.count(), 1)

    def test_failed_record_leaves_no_player_row(self):
        self.write(xlog_line(name='newbie')
                   + xlog_line(name='alice', start=in_window(5)))
        real_create = Game.objects.create

        def create_unless_newbie(**kwargs):
            if kwargs['player'].name == 'newbie':
                raise RuntimeError('simulated database error')
            return real_create(**kwargs)

        with mock.patch.object(Game.objects, 'create',
                               side_effect=create_unless_newbie), \
                self.assertLogs(level='ERROR'):
            counts = import_from_file(self.path, self.src)
        self.assertEqual(counts[BAD], 1)
        self.assertEqual(counts[ADDED], 1)
        # the savepoint rolled back the Player created for the failed record
        self.assertFalse(Player.objects.filter(name='newbie').exists())
        self.assertTrue(Player.objects.filter(name='alice').exists())

    def test_wizard_explore_and_out_of_window_games_are_filtered(self):
        before_start = int(tnnt.settings.TOURNAMENT_START.timestamp()) - 86400
        near_end = int(tnnt.settings.TOURNAMENT_END.timestamp()) - 100
        self.write(xlog_line(flags='0x1')
                   + xlog_line(flags='0x2')
                   + xlog_line(start=before_start)
                   + xlog_line(start=near_end, realtime='1000'))
        counts = import_from_file(self.path, self.src)
        self.assertEqual(counts[FILTERED], 4)
        self.assertEqual(Game.objects.count(), 0)

    def test_won_and_mines_soko_flags(self):
        self.write(xlog_line(achieve='0x700', death='ascended')
                   + xlog_line(achieve='0x20', start=in_window(5)))
        import_from_file(self.path, self.src)
        won = Game.objects.get(death='ascended')
        self.assertTrue(won.won)
        self.assertTrue(won.mines_soko)
        self.assertIsNone(won.normalized_death)   # ascensions are rejected
        splat = Game.objects.get(death='killed by a jackal')
        self.assertTrue(splat.splatted)
        self.assertEqual(splat.normalized_death, 'killed by a jackal')

    def test_file_mode_reads_unterminated_last_line_and_detects_source(self):
        self.write(xlog_line(server='eu.hardfought.org').rstrip('\n'))
        counts = import_from_file(self.path, None)
        self.assertEqual(counts[ADDED], 1)
        self.assertEqual(Game.objects.get().source.server, 'hfe')


class FakeResponse:
    """Minimal stand-in for requests.Response as used by sync_local_file."""

    def __init__(self, status_code, headers=None, body=b'', fail=False):
        self.status_code = status_code
        self.headers = headers or {}
        self.body = body
        self.fail = fail

    def iter_content(self, chunk_size):
        yield self.body[:3]
        if self.fail:
            raise requests.ConnectionError('dropped')
        yield self.body[3:]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class SyncLocalFileTests(TestCase):
    URL = 'https://example.org/xlogfile'

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.object(tnnt.settings, 'XLOG_DIR', tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.path = Path(tmp.name) / 'test.xlog'
        self.path.write_bytes(b'old data\n')

    def sync(self, response):
        with mock.patch.object(pollxlogs.requests, 'get',
                               return_value=response) as get:
            result = sync_local_file(self.URL, 'test.xlog')
        return result, get

    def test_206_from_local_length_is_appended(self):
        resp = FakeResponse(206, {'Content-Range': 'bytes 9-15/16'},
                            b'new one\n')
        result, get = self.sync(resp)
        self.assertTrue(result)
        self.assertEqual(self.path.read_bytes(), b'old data\nnew one\n')
        headers = get.call_args.kwargs['headers']
        self.assertEqual(headers['Range'], 'bytes=9-')
        self.assertEqual(headers['Accept-Encoding'], 'identity')
        self.assertIn('timeout', get.call_args.kwargs)

    def test_200_with_non_empty_local_copy_is_not_appended(self):
        with self.assertLogs(level='WARNING'):
            result, _ = self.sync(FakeResponse(200, body=b'whole file\n'))
        self.assertFalse(result)
        self.assertEqual(self.path.read_bytes(), b'old data\n')

    def test_200_with_empty_local_copy_is_the_whole_file(self):
        # Apache ignores Range on an empty file and answers 200; from an
        # empty local copy the whole file is exactly the requested range.
        self.path.write_bytes(b'')
        result, get = self.sync(FakeResponse(200, body=b''))
        self.assertTrue(result)
        self.assertEqual(self.path.read_bytes(), b'')
        self.assertEqual(get.call_args.kwargs['headers']['Range'], 'bytes=0-')
        result, _ = self.sync(FakeResponse(200, body=b'first game\n'))
        self.assertTrue(result)
        self.assertEqual(self.path.read_bytes(), b'first game\n')

    def test_206_with_wrong_range_is_not_appended(self):
        resp = FakeResponse(206, {'Content-Range': 'bytes 0-15/16'},
                            b'whole file\n')
        with self.assertLogs(level='ERROR'):
            result, _ = self.sync(resp)
        self.assertFalse(result)
        self.assertEqual(self.path.read_bytes(), b'old data\n')

    def test_416_nothing_new_is_fine(self):
        result, _ = self.sync(FakeResponse(416,
                                           {'Content-Range': 'bytes */9'}))
        self.assertTrue(result)
        self.assertEqual(self.path.read_bytes(), b'old data\n')

    def test_416_shorter_remote_is_warned_about(self):
        with self.assertLogs(level='WARNING') as logs:
            result, _ = self.sync(FakeResponse(416,
                                               {'Content-Range': 'bytes */3'}))
        self.assertTrue(result)
        self.assertTrue(any('truncated or rotated' in m for m in logs.output))

    def test_connection_error_returns_false(self):
        with mock.patch.object(pollxlogs.requests, 'get',
                               side_effect=requests.ConnectionError('down')), \
                self.assertLogs(level='ERROR'):
            self.assertFalse(sync_local_file(self.URL, 'test.xlog'))
        self.assertEqual(self.path.read_bytes(), b'old data\n')

    def test_interrupted_download_keeps_prefix(self):
        resp = FakeResponse(206, {'Content-Range': 'bytes 9-15/16'},
                            b'new one\n', fail=True)
        with self.assertLogs(level='ERROR'):
            result, _ = self.sync(resp)
        self.assertFalse(result)
        # the bytes that did arrive are a valid prefix; the next poll
        # resumes from here
        self.assertEqual(self.path.read_bytes(), b'old data\nnew')


class HandleTests(TestCase):
    fixtures = ['sources']

    def test_one_failing_source_does_not_stop_the_others(self):
        def sync(url, local_file):
            if local_file.startswith('hdf'):
                raise RuntimeError('simulated failure')
            return True

        imported = []
        with mock.patch.object(pollxlogs, 'sync_local_file',
                               side_effect=sync), \
                mock.patch.object(pollxlogs, 'import_records',
                                  side_effect=lambda s: imported.append(
                                      s.server)), \
                self.assertLogs(level='ERROR'):
            with self.assertRaises(CommandError) as cm:
                pollxlogs.Command().handle(file=None)
        self.assertEqual(sorted(imported), ['hdf', 'hfa', 'hfe'])
        self.assertIn('hdf sync', str(cm.exception))

    def test_all_sources_ok_exits_cleanly(self):
        with mock.patch.object(pollxlogs, 'sync_local_file',
                               return_value=True), \
                mock.patch.object(pollxlogs, 'import_records'):
            pollxlogs.Command().handle(file=None)
