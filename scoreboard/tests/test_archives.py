"""
Every local script, stylesheet and image that a full archive page loads
must exist. The 2019 and 2020 archives were published without
js/scbd-filter.js (the Scoring Breakdown filter on player and clan pages)
and 2020's countdown.js, and nothing noticed until a log check on
2026-11-01: those pages had been 404ing them since the archive move.
"""
import os
import re
import unittest
from collections import defaultdict
from pathlib import Path

from django.test import SimpleTestCase

import tnnt.settings

STATIC = Path(tnnt.settings.BASE_DIR) / 'tnnt' / 'static'
ARCHIVES = STATIC / 'archives'

ASSET_EXTENSIONS = ('js', 'css', 'ico', 'svg', 'png', 'jpg', 'jpeg', 'gif',
                    'woff', 'woff2')
# src="..." / href="..." naming a local asset; an optional ?v= query is
# dropped, and anything with a ':' (http:, data:, mailto:) is not local.
# Case-sensitive on purpose: the archive markup is all lowercase, and
# re.IGNORECASE made the scan of ~380 MB of pages four times slower.
ASSET_REF = re.compile(
    rb'(?:src|href)="([^"#:?]+\.(?:' +
    '|'.join(ASSET_EXTENSIONS).encode() + rb'))(?:\?[^"]*)?"')
BASE_HREF = re.compile(rb'<base href="([^"]*)"')


def is_page(path):
    """
    Whether `path` is a full HTML page: not an asset, and with <html in its
    first 512 bytes, the rule ArchiveFileView uses for extensionless files
    (2021-2022 pages have no extension, and some have a dot in the name).
    The *-header.html fragments of 2018-2020 have no <html> and are not
    pages; their relative logo paths never resolved.
    """
    if path.suffix.lstrip('.').lower() in ASSET_EXTENSIONS:
        return False
    try:
        with open(path, 'rb') as fh:
            return b'<html' in fh.read(512).lower()
    except OSError:
        return False


def resolve(page, base, ref):
    """The file that `ref` on `page` (with <base href> `base`) points to."""
    if ref.startswith('/static/'):
        return STATIC / ref[len('/static/'):]
    if ref.startswith('/'):
        return STATIC / ref.lstrip('/')
    return Path(os.path.normpath(page.parent / base / ref))


@unittest.skipUnless(ARCHIVES.is_dir(), 'no archives in this checkout')
class ArchiveAssetTests(SimpleTestCase):

    def test_every_asset_a_page_loads_exists(self):
        missing = defaultdict(list)
        for dirpath, dirnames, filenames in os.walk(ARCHIVES):
            dirnames[:] = [d for d in dirnames if d != 'xlogfiles']
            for name in filenames:
                page = Path(dirpath) / name
                if not is_page(page):
                    continue
                data = page.read_bytes()
                # <base> is in the <head>
                match = BASE_HREF.search(data, 0, 4096)
                base = match.group(1).decode() if match else ''
                for ref in set(ASSET_REF.findall(data)):
                    target = resolve(page, base, ref.decode())
                    if not target.exists():
                        missing[str(target.relative_to(STATIC))].append(
                            str(page.relative_to(ARCHIVES)))
        report = ['%s (%d pages, e.g. %s)' % (target, len(pages), pages[0])
                  for target, pages in sorted(missing.items())]
        self.assertEqual(report, [])
