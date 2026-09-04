"""
IP lookup helpers in tnnt.hardfought_utils.

The SSH / sqlite layer is mocked out. These tests pin down how many
round trips a lookup costs, how results from the three servers merge,
and how remote queries are built for the sqlite3 CLI, which takes no
bound parameters.
"""
import shlex
from unittest import mock

from django.test import SimpleTestCase

from tnnt import hardfought_utils


def rows(*triples):
    """Rows as query_remote_ip_db() returns them."""
    return [{'username': name, 'ip_address': ip, 'last_seen': seen}
            for name, ip, seen in triples]


class BatchedLastIpTests(SimpleTestCase):

    def test_one_query_per_server_however_many_players(self):
        answers = {
            'us': rows(('alice', '10.0.0.1', 100), ('bob', '10.0.0.2', 50)),
            'eu': rows(('alice', '10.1.0.1', 200)),
            'au': rows(('carol', '10.2.0.3', 30)),
        }
        with mock.patch.object(
                hardfought_utils, 'query_remote_ip_db',
                side_effect=lambda server, query, params: answers[server]
        ) as query:
            ips = hardfought_utils.get_players_last_ips(
                ['dave', 'alice', 'bob', 'carol'])

        self.assertEqual([c.args[0] for c in query.call_args_list],
                         ['us', 'eu', 'au'])
        # every name goes into a single IN (...) list, sorted
        self.assertEqual(query.call_args_list[0].args[2],
                         ('alice', 'bob', 'carol', 'dave'))
        self.assertIn('IN (?, ?, ?, ?)', query.call_args_list[0].args[1])
        # alice: EU is newer than US; dave: no record anywhere
        self.assertEqual(ips, {'alice': '10.1.0.1', 'bob': '10.0.0.2',
                               'carol': '10.2.0.3'})

    def test_no_names_means_no_queries(self):
        with mock.patch.object(hardfought_utils,
                               'query_remote_ip_db') as query:
            self.assertEqual(hardfought_utils.get_players_last_ips([]), {})
        query.assert_not_called()

    def test_duplicates_collapse_and_long_lists_are_chunked(self):
        chunk = hardfought_utils.IP_LOOKUP_CHUNK
        names = ['p%04d' % i for i in range(chunk + 1)]
        with mock.patch.object(hardfought_utils, 'query_remote_ip_db',
                               return_value=[]) as query:
            hardfought_utils.get_players_last_ips(names + names)
        # two chunks x three servers
        self.assertEqual(query.call_count, 6)
        sizes = sorted({len(c.args[2]) for c in query.call_args_list})
        self.assertEqual(sizes, [1, chunk])
        for call in query.call_args_list:
            self.assertEqual(call.args[1].count('?'), len(call.args[2]))

    def test_single_player_wrapper(self):
        with mock.patch.object(hardfought_utils, 'query_remote_ip_db',
                               return_value=rows(('alice', '10.0.0.1', 1))):
            self.assertEqual(hardfought_utils.get_player_last_ip('alice'),
                             '10.0.0.1')
        with mock.patch.object(hardfought_utils, 'query_remote_ip_db',
                               return_value=[]):
            self.assertIsNone(hardfought_utils.get_player_last_ip('alice'))

    def test_malformed_row_is_logged_not_fatal(self):
        with mock.patch.object(hardfought_utils, 'query_remote_ip_db',
                               return_value=[{'username': 'alice'}]), \
                self.assertLogs(level='ERROR'):
            self.assertEqual(
                hardfought_utils.get_players_last_ips(['alice']), {})


class RemoteQueryTests(SimpleTestCase):
    """
    The sqlite3 CLI takes no bound parameters, so remote queries are built
    by substituting the values in. The SQL is the last argument of the
    remote command, which is shell-quoted as a whole.
    """

    def remote_sql(self, query, params):
        done = mock.Mock(returncode=0, stdout='[]', stderr='')
        with mock.patch.object(hardfought_utils.subprocess, 'run',
                               return_value=done) as run:
            result = hardfought_utils.query_remote_ip_db('eu', query, params)
        self.assertEqual(result, [])
        run.assert_called_once()
        remote_cmd = run.call_args.args[0][-1]
        return shlex.split(remote_cmd)[-1]

    def test_placeholders_are_filled_in_order(self):
        sql = self.remote_sql('SELECT 1 WHERE u IN (?, ?, ?)',
                              ('a', 'b', 'c'))
        self.assertEqual(sql, "SELECT 1 WHERE u IN ('a', 'b', 'c')")

    def test_question_mark_in_a_value_is_not_a_placeholder(self):
        sql = self.remote_sql('SELECT 1 WHERE a = ? AND b = ?',
                              ('a?b', 'c'))
        self.assertEqual(sql, "SELECT 1 WHERE a = 'a?b' AND b = 'c'")

    def test_quote_in_a_value_is_escaped(self):
        sql = self.remote_sql('SELECT 1 WHERE a = ?', ("o'brien",))
        self.assertEqual(sql, "SELECT 1 WHERE a = 'o''brien'")

    def test_placeholder_count_mismatch_is_refused(self):
        with mock.patch.object(hardfought_utils.subprocess, 'run') as run, \
                self.assertLogs(level='ERROR'):
            result = hardfought_utils.query_remote_ip_db(
                'eu', 'SELECT 1 WHERE a = ?', ('a', 'b'))
        self.assertEqual(result, [])
        run.assert_not_called()
