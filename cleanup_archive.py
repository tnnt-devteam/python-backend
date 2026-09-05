#!/usr/bin/env python3
"""
cleanup_archive.py - Post-process archived TNNT tournament pages

Usage: python cleanup_archive.py [year]

This script processes the mirrored tournament pages to:
1. Fix logo link to point to / (main site)
2. Fix title link to point to index.html (archive home)
3. Remove login form functionality
4. Remove admin panel links
5. Add archive banner below header
6. Change CSS to archive gray color scheme
7. Point each trophy progress tracker at its archived games file (see
   archive_trophy_games below)

The trophy grid's clickable cells normally call the live API by database
id, which is useless in an archive (ids are reissued every tournament).
`./manage.py archive_trophy_games <year>` writes one JSON file per player
and clan under <archive>/api/trophy-grid-games/, and step 7 stamps the
file's URL on each page's grid container (`data-archive-games`), which
trophy-grid.js reads instead of the API. Run that command before this
script, while the tournament's data is still in the database.
"""

import html
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

def get_archive_dir(year):
    """Get the archive directory path for a given year."""
    script_dir = Path(__file__).parent
    return script_dir / 'tnnt' / 'static' / 'archives' / str(year)

def process_css(css_path, year):
    """Modify CSS to use archive gray color scheme."""
    if not css_path.exists():
        print(f"  Warning: CSS file not found: {css_path}")
        return

    print(f"  Processing CSS: {css_path}")
    content = css_path.read_text()

    # Change background colors from blue to gray
    # Body background: #003 -> #111
    content = re.sub(
        r'background-color:\s*#003\b',
        'background-color: #111',
        content
    )

    # Table header background: #237 -> #555
    content = re.sub(
        r'background-color:\s*#237\b',
        'background-color: #555',
        content
    )

    css_path.write_text(content)
    print("    - Updated color scheme to archive gray")

def process_html(html_path, year):
    """Process an HTML file to apply archive modifications."""
    print(f"  Processing: {html_path.name}")
    content = html_path.read_text()
    modified = False

    # 0. Add UTF-8 charset meta tag if missing
    if '<meta charset=' not in content.lower() and '<head>' in content:
        content = content.replace('<head>', '<head>\n  <meta charset="UTF-8">')
        modified = True
        print("    - Added UTF-8 charset")

    # 1. Fix title link to point to index.html (for archive home)
    # Change href="/" in titlelink to href="index.html"
    if '<a id="titlelink" href="/">' in content:
        content = content.replace(
            '<a id="titlelink" href="/">',
            '<a id="titlelink" href="index.html">'
        )
        modified = True
        print("    - Fixed title link")

    # 1b. Fix logo link to point to / (main site)
    # The logo in #logo td should link back to main site, not archive home
    # wget converts it to index.html, we need to change it back to /
    logo_pattern = r'(<td id="logo"[^>]*>\s*<a href=")index\.html(")'
    if re.search(logo_pattern, content):
        content = re.sub(logo_pattern, r'\1/\2', content)
        modified = True
        print("    - Fixed logo link to main site")

    # 1c. Fix ARCHIVES nav link to point to /archives (main site)
    # The archives link should go to the main site, not the archived archives page
    if 'href="archives.html"' in content:
        content = content.replace('href="archives.html"', 'href="/archives"')
        modified = True
        print("    - Fixed ARCHIVES link to main site")

    # 2. Add archive banner if not already present
    banner = f'<h2>{year} ARCHIVE</h2>'
    if banner not in content:
        # Insert banner after </table> within header, before </header>
        # Pattern: </table>\s*(</header>)
        pattern = r'(</table>\s*)(</header>)'
        replacement = r'\1      <tr>\n          <td><br />' + banner + r'</td>\n      </tr>\n\2'
        new_content = re.sub(pattern, replacement, content)
        if new_content != content:
            content = new_content
            modified = True
            print("    - Added archive banner")

    # 3. Comment out login forms
    # Match <form method="post"> ... </form> containing login elements
    if '<form method="post">' in content and 'csrfmiddlewaretoken' in content:
        # Comment out the form (avoid double commenting)
        if '<!-- <form method="post">' not in content:
            content = re.sub(
                r'(<form method="post">.*?</form>)',
                r'<!-- \1 -->',
                content,
                flags=re.DOTALL
            )
            modified = True
            print("    - Commented out login form")

    # 3b. Fix double --> from previous comment processing
    if '</form> --> -->' in content:
        content = content.replace('</form> --> -->', '</form> -->')
        modified = True
        print("    - Fixed stray comment closing tag")

    # 4. Remove admin panel link from navigation
    if 'admin-panel' in content:
        content = re.sub(
            r'<a href="[^"]*admin-panel[^"]*"[^>]*>[^<]*</a>\s*',
            '',
            content
        )
        modified = True
        print("    - Removed admin panel link")

    # 5. Remove MY CLAN link from navigation (only shown when logged in)
    if 'clanmgmt' in content and 'MY CLAN' in content:
        content = re.sub(
            r'<a href="[^"]*clanmgmt[^"]*"[^>]*>MY CLAN</a>\s*',
            '',
            content
        )
        modified = True
        print("    - Removed MY CLAN link")

    # 6. Point the trophy progress tracker at the archived games file.
    # Player pages live in player/, clan pages in clan/; the entity's exact
    # name is the page title ("TNNT :: <name>"), HTML-escaped.
    entity_type = html_path.parent.name
    if 'class="trophy-grid-container"' in content and \
            'data-archive-games' not in content and \
            entity_type in ('player', 'clan'):
        title = re.search(r'<title>TNNT :: (.*?)</title>', content)
        if title is None:
            print("    - WARNING: trophy grid but no title, cannot link "
                  "its games file")
        else:
            name = html.unescape(title.group(1))
            games_file = html_path.parent.parent / 'api' / \
                'trophy-grid-games' / entity_type / (name + '.json')
            if not games_file.exists():
                print(f"    - WARNING: {games_file} is missing; run "
                      f"./manage.py archive_trophy_games {year}")
            url = '../api/trophy-grid-games/%s/%s.json' % (
                entity_type, quote(name, safe=''))
            content = content.replace(
                '<div class="trophy-grid-container">',
                '<div class="trophy-grid-container" data-archive-games="%s">'
                % html.escape(url, quote=True), 1)
            modified = True
            print("    - Linked trophy grid to its archived games file")

    if modified:
        html_path.write_text(content)

def process_archive(year):
    """Process all files in the archive directory."""
    archive_dir = get_archive_dir(year)

    if not archive_dir.exists():
        print(f"Error: Archive directory not found: {archive_dir}")
        sys.exit(1)

    print(f"Processing archive for year {year}")
    print(f"Directory: {archive_dir}")
    print()

    # Process CSS file
    css_path = archive_dir / 'static' / 'css' / 'default.css'
    process_css(css_path, year)
    print()

    # Process all HTML files
    html_count = 0
    for html_path in archive_dir.rglob('*.html'):
        process_html(html_path, year)
        html_count += 1

    print()
    print(f"Processed {html_count} HTML files")
    print("Archive cleanup complete!")

def main():
    if len(sys.argv) > 1:
        year = sys.argv[1]
    else:
        import datetime
        year = datetime.datetime.now().year

    process_archive(year)

if __name__ == '__main__':
    main()
