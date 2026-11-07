"""
Every local script, stylesheet and image that a full archive page loads
must exist. The 2019 and 2020 archives were published without
js/scbd-filter.js (the Scoring Breakdown filter on player and clan pages)
and 2020's countdown.js, and nothing noticed until a log check on
2026-11-01: those pages had been 404ing them since the archive move.
"""
import html
import os
import re
import unittest
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote

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


# <a href="..."> on a page; the archived markup double-quotes every href.
PAGE_LINK = re.compile(rb'<a\b[^>]*?\shref="([^"]*)"')
YEAR_LINK = re.compile(r'/archives/(\d{4})/(.*)')
# 2018-2020 predate the move to tnnt.org and still link hardfought.org-era
# pages that were never archived (clanmgmt/, /nethack, ...). Every later
# year was mirrored from tnnt.org, so none of its links may be dead.
FIRST_LINK_CHECKED_YEAR = 2021


def link_target(page, base, href):
    """
    The file a browser and ArchiveFileView serve for `href` on `page` (with
    <base href> `base`), or None when the link leaves the archives (http:,
    mailto:, a fragment, a live-site path like /archives or /). Entities and
    %-escapes are decoded and a query is dropped, as the browser and Django
    do; a literal '?' starts the query, an escaped one (%3F) is part of the
    file name (2025's "?show_all=..." pages).
    """
    href = html.unescape(href).split('#', 1)[0].split('?', 1)[0]
    if not href or ':' in href.split('/', 1)[0]:
        return None
    path = unquote(href)
    if path.startswith('/'):
        match = YEAR_LINK.fullmatch(path)
        if not match:
            return None
        return ARCHIVES / match.group(1) / match.group(2)
    return Path(os.path.normpath(page.parent / html.unescape(base) / path))


def link_resolves(target):
    """
    Whether ArchiveFileView would serve `target`: an existing file inside a
    year's archive, or the year directory itself (its index.html); any other
    directory is a 404.
    """
    try:
        relative = target.relative_to(ARCHIVES)
    except ValueError:
        return False
    if not relative.parts or not re.fullmatch(r'\d{4}', relative.parts[0]):
        return False
    if target.is_dir():
        return len(relative.parts) == 1
    return target.is_file()


@unittest.skipUnless(ARCHIVES.is_dir(), 'no archives in this checkout')
class ArchivePageLinkTests(SimpleTestCase):
    """
    Every link between archive pages leads to a page. wget mis-converted
    some links when 2022 was mirrored: the four clans whose names start
    with "clan" were linked as clanclan%20<rest> on the clans, leaderboards,
    players and trophies pages, and the clan and player pages pointed their
    title link at index.html and TROPHIES at trophies inside clan/ and
    player/ (repaired 2026-11-06).
    """

    def test_every_page_link_resolves(self):
        broken = defaultdict(list)
        years = [y for y in os.listdir(ARCHIVES)
                 if re.fullmatch(r'\d{4}', y)
                 and int(y) >= FIRST_LINK_CHECKED_YEAR]
        for year in sorted(years):
            for dirpath, dirnames, filenames in os.walk(ARCHIVES / year):
                dirnames[:] = [d for d in dirnames
                               if d not in ('xlogfiles', 'static', 'api')]
                for name in filenames:
                    page = Path(dirpath) / name
                    if not is_page(page):
                        continue
                    data = page.read_bytes()
                    match = BASE_HREF.search(data, 0, 4096)
                    base = match.group(1).decode() if match else ''
                    for href in set(PAGE_LINK.findall(data)):
                        href = href.decode('utf-8', 'replace')
                        target = link_target(page, base, href)
                        if target is not None and not link_resolves(target):
                            broken[href].append(
                                str(page.relative_to(ARCHIVES)))
        report = ['%s (%d pages, e.g. %s)' % (href, len(pages), pages[0])
                  for href, pages in sorted(broken.items())]
        self.assertEqual(report, [])
