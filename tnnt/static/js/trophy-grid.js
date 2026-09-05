/**
 * Trophy Grid Interactive Functionality
 * Handles clickable cells and game details modal
 *
 * Everything that comes back from the API (player names, dumplog URLs,
 * dates) is placed in the document with textContent or a property
 * assignment, never by building markup, so nothing in the data can be
 * interpreted as HTML.
 */

(function() {
  'use strict';

  // Static modal skeleton. It carries no data, so a template is safe here.
  const modalHTML = `
    <div id="trophy-grid-modal" class="trophy-modal trophy-modal-hidden">
      <div class="trophy-modal-overlay"></div>
      <div class="trophy-modal-content">
        <div class="trophy-modal-header">
          <h3 id="modal-title"></h3>
          <button class="trophy-modal-close">&times;</button>
        </div>
        <div class="trophy-modal-body">
          <div id="modal-loading" class="modal-loading"></div>
          <div id="modal-games" class="modal-games-hidden"></div>
        </div>
      </div>
    </div>
  `;

  const LOADING_TEXT = 'Loading games...';
  const COLUMNS = ['Player', 'Date', 'Score', 'Turns', 'Dumplog'];

  // One entry per list in the API response, in display order. The symbols
  // match the trophy grid legend in singleplayerorclan.html.
  const SECTIONS = [
    {key: 'mines_soko', label: 'Mines + Soko Complete',
     symbolClass: 'sym-mines', symbol: '⛏'},
    {key: 'male_ascensions', label: 'Male Ascensions',
     symbolClass: 'sym-male', symbol: '♂'},
    {key: 'female_ascensions', label: 'Female Ascensions',
     symbolClass: 'sym-female', symbol: '♀'}
  ];

  // Create an element with an optional class and text content.
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) {
      node.className = className;
    }
    if (text !== undefined && text !== null) {
      node.textContent = text;
    }
    return node;
  }

  // One table row for a game.
  function gameRow(game) {
    const row = el('tr');
    row.appendChild(el('td', null, game.player__name || ''));
    row.appendChild(el('td', null, game.endtime || ''));
    row.appendChild(el('td', null, (game.points || 0).toLocaleString()));
    row.appendChild(el('td', null, (game.turns || 0).toLocaleString()));
    const linkCell = el('td');
    if (game.dumplog) {
      const link = el('a', null, 'View');
      link.href = game.dumplog;
      link.target = '_blank';
      link.rel = 'noopener';
      linkCell.appendChild(link);
    }
    row.appendChild(linkCell);
    return row;
  }

  // Heading plus table for one section of the response.
  function gamesSection(section, games) {
    const fragment = document.createDocumentFragment();

    const heading = el('h4');
    const symbols = el('span', 'progress-symbols');
    symbols.appendChild(el('span', section.symbolClass, section.symbol));
    heading.appendChild(symbols);
    heading.appendChild(document.createTextNode(
      ' ' + section.label + ' (' + games.length + ')'));
    fragment.appendChild(heading);

    const table = el('table', 'games-table');
    const headerRow = el('tr');
    COLUMNS.forEach(function(column) {
      headerRow.appendChild(el('th', null, column));
    });
    const thead = el('thead');
    thead.appendChild(headerRow);
    table.appendChild(thead);
    const tbody = el('tbody');
    games.forEach(function(game) {
      tbody.appendChild(gameRow(game));
    });
    table.appendChild(tbody);
    fragment.appendChild(table);

    return fragment;
  }

  // Initialize when DOM is ready
  document.addEventListener('DOMContentLoaded', function() {
    // Check if there are any clickable cells on the page
    const cells = document.querySelectorAll('.clickable-cell');
    if (cells.length === 0) {
      return; // No trophy grid on this page, don't initialize
    }

    // On an archived page (tnnt/static/archives/<year>/) the grid
    // container carries data-archive-games: the URL of a static JSON file
    // with every combo's games for this player or clan, written by
    // ./manage.py archive_trophy_games and wired up by cleanup_archive.py.
    // The live API cannot serve an archive: it looks entities up by
    // database id, and ids are reissued every tournament.
    const container = cells[0].closest('.trophy-grid-container');
    const archiveUrl = container ? container.dataset.archiveGames : undefined;
    let archiveData = null; // promise for the parsed archive file

    // Check if modal already exists (prevent duplicate initialization)
    if (document.getElementById('trophy-grid-modal')) {
      return;
    }

    // Add modal to page
    document.body.insertAdjacentHTML('beforeend', modalHTML);

    const modal = document.getElementById('trophy-grid-modal');
    const modalTitle = document.getElementById('modal-title');
    const modalLoading = document.getElementById('modal-loading');
    const modalGames = document.getElementById('modal-games');
    const closeBtn = modal.querySelector('.trophy-modal-close');
    const overlay = modal.querySelector('.trophy-modal-overlay');

    // Each click gets a number; a response for anything but the latest
    // click is dropped, so a slow earlier request cannot overwrite the
    // games of the cell the user clicked last.
    let latestRequest = 0;

    // Close modal handlers
    closeBtn.addEventListener('click', closeModal);
    overlay.addEventListener('click', closeModal);

    // ESC key to close
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && !modal.classList.contains('trophy-modal-hidden')) {
        closeModal();
      }
    });

    function closeModal() {
      modal.classList.add('trophy-modal-hidden');
      modalGames.textContent = '';
    }

    function openModal(title) {
      modalTitle.textContent = title;
      modalLoading.textContent = LOADING_TEXT;
      modalLoading.classList.remove('modal-loading-hidden');
      modalGames.classList.add('modal-games-hidden');
      modalGames.textContent = '';
      modal.classList.remove('trophy-modal-hidden');
    }

    function showError(message) {
      modalLoading.textContent = '';
      modalLoading.appendChild(
        el('p', 'error-msg', 'Error loading games: ' + message));
    }

    function displayGames(data) {
      modalLoading.classList.add('modal-loading-hidden');
      modalGames.classList.remove('modal-games-hidden');
      modalGames.textContent = '';

      const games = data.games || {};
      let shown = 0;
      SECTIONS.forEach(function(section) {
        const list = games[section.key];
        if (list && list.length > 0) {
          modalGames.appendChild(gamesSection(section, list));
          shown += 1;
        }
      });

      if (shown === 0) {
        modalGames.appendChild(
          el('p', 'no-games-msg', 'No games found for this combination.'));
      }
    }

    // Resolve to the parsed body, or reject with the server's error message
    // (the API answers 400/404 with {"error": "..."}) or the status code.
    function parseResponse(response) {
      return response.json()
        .catch(function() { return {}; })
        .then(function(body) {
          if (!response.ok) {
            throw new Error(body.error || ('server returned ' + response.status));
          }
          return body;
        });
    }

    // Archive mode: fetch the page's games file once, then answer every
    // click from it in the shape the live API uses ({games: {...}}). A
    // failed fetch is forgotten so the next click retries it.
    function archiveGames(comboKey) {
      if (!archiveData) {
        archiveData = fetch(archiveUrl).then(parseResponse);
        archiveData.catch(function() { archiveData = null; });
      }
      return archiveData.then(function(data) {
        const combos = data.combos || {};
        return {games: combos[comboKey] || {}};
      });
    }

    // Add click handlers to trophy grid cells (cells already declared above)
    cells.forEach(function(cell) {
      cell.addEventListener('click', function() {
        const role = this.dataset.role;
        const raceAlign = this.dataset.raceAlign;
        const entityType = this.dataset.entityType;
        const entityId = this.dataset.entityId;

        // Split race-align
        const [race, align] = raceAlign.split('-');

        // Open modal
        openModal(role + '-' + race + '-' + align + ' Games');

        const request = ++latestRequest;
        const params = new URLSearchParams({
          entity_type: entityType,
          entity_id: entityId,
          role: role,
          race: race,
          align: align
        });

        const lookup = archiveUrl
          ? archiveGames(role + '-' + race + '-' + align)
          : fetch('/api/trophy-grid-games/?' + params.toString())
              .then(parseResponse);

        lookup
          .then(function(data) {
            if (request === latestRequest) {
              displayGames(data);
            }
          })
          .catch(function(error) {
            if (request === latestRequest) {
              showError(error.message);
            }
          });
      });
    });
  });
})();
