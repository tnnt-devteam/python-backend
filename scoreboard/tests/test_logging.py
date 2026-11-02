"""The server log must survive logrotate's weekly rename.

logrotate rotates /var/log/tnnt/*.log with "create": tnnt_server.log is
renamed to tnnt_server.log.1 and an empty tnnt_server.log is created. The
web server (runserver) is a long-running process, so a plain FileHandler
kept writing to the renamed file, and a week later to a deleted inode once
the next rotation compressed it (found 2026-11-01).
"""
import logging
import os
import tempfile

from django.test import SimpleTestCase
from django.utils.module_loading import import_string

import tnnt.settings


class LogRotationTests(SimpleTestCase):
    """The configured file handler follows a rename of its log file."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, 'tnnt_server.log')
        handler_class = import_string(
            tnnt.settings.LOGGING['handlers']['file']['class'])
        self.handler = handler_class(self.path)
        self.logger = logging.getLogger('tnnt.tests.log_rotation')
        self.logger.propagate = False
        self.logger.setLevel(logging.INFO)
        self.logger.addHandler(self.handler)
        self.addCleanup(self.handler.close)
        self.addCleanup(self.logger.removeHandler, self.handler)

    def read(self, path):
        """Return the contents of a log file."""
        with open(path) as fh:
            return fh.read()

    def rotate(self):
        """Rotate like logrotate: rename, then create the new file."""
        os.rename(self.path, self.path + '.1')
        open(self.path, 'a').close()

    def test_lines_after_rotation_go_to_the_new_file(self):
        self.logger.info('before rotation')
        self.rotate()
        self.logger.info('after rotation')
        self.assertEqual(self.read(self.path), 'after rotation\n')
        self.assertEqual(self.read(self.path + '.1'), 'before rotation\n')

    def test_rotated_file_deleted(self):
        # the next rotation compresses .1 into .2.gz and removes it
        self.logger.info('first week')
        self.rotate()
        os.remove(self.path + '.1')
        self.logger.info('second week')
        self.assertEqual(self.read(self.path), 'second week\n')
