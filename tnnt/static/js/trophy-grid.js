/**
 * Trophy Grid Interactive Functionality
 * Handles clickable cells and game details modal
 */

(function() {
  'use strict';

  // Modal HTML structure
  const modalHTML = `
    <div id="trophy-grid-modal" class="trophy-modal trophy-modal-hidden">
      <div class="trophy-modal-overlay"></div>
      <div class="trophy-modal-content">
        <div class="trophy-modal-header">
          <h3 id="modal-title"></h3>
          <button class="trophy-modal-close">&times;</button>
        </div>
        <div class="trophy-modal-body">
          <div id="modal-loading" class="modal-loading">
            Loading games...
          </div>
          <div id="modal-games" class="modal-games-hidden"></div>
        </div>
      </div>
    </div>
  `;

  // Initialize when DOM is ready
  document.addEventListener('DOMContentLoaded', function() {
    // Check if there are any clickable cells on the page
    const cells = document.querySelectorAll('.clickable-cell');
    if (cells.length === 0) {
      return; // No trophy grid on this page, don't initialize
    }

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
      modalGames.innerHTML = '';
    }

    function openModal(title) {
      modalTitle.textContent = title;
      modalLoading.classList.remove('modal-loading-hidden');
      modalGames.classList.add('modal-games-hidden');
      modalGames.innerHTML = '';
      modal.classList.remove('trophy-modal-hidden');
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
        openModal(`${role}-${race}-${align} Games`);

        // Fetch games from API
        const url = `/api/trophy-grid-games/?entity_type=${entityType}&entity_id=${entityId}&role=${role}&race=${race}&align=${align}`;

        fetch(url)
          .then(response => response.json())
          .then(data => {
            displayGames(data);
          })
          .catch(error => {
            modalLoading.innerHTML = '<p class="error-msg">Error loading games: ' + error.message + '</p>';
          });
      });
    });

    function displayGames(data) {
      modalLoading.classList.add('modal-loading-hidden');
      modalGames.classList.remove('modal-games-hidden');

      const games = data.games;
      let html = '';

      // Mines+Soko section
      if (games.mines_soko && games.mines_soko.length > 0) {
        html += '<h4><span class="progress-symbols"><span class="sym-mines">✓</span></span> Mines + Soko Complete (' + games.mines_soko.length + ')</h4>';
        html += '<table class="games-table">';
        html += '<thead><tr><th>Player</th><th>Date</th><th>Score</th><th>Turns</th><th>Dumplog</th></tr></thead>';
        html += '<tbody>';
        games.mines_soko.forEach(function(game) {
          html += '<tr>';
          html += '<td>' + game.player__name + '</td>';
          html += '<td>' + (game.endtime || '') + '</td>';
          html += '<td>' + (game.points || 0).toLocaleString() + '</td>';
          html += '<td>' + (game.turns || 0).toLocaleString() + '</td>';
          html += '<td><a href="' + game.dumplog + '" target="_blank">View</a></td>';
          html += '</tr>';
        });
        html += '</tbody></table>';
      }

      // Male ascensions section
      if (games.male_ascensions && games.male_ascensions.length > 0) {
        html += '<h4><span class="progress-symbols"><span class="sym-male">♂</span></span> Male Ascensions (' + games.male_ascensions.length + ')</h4>';
        html += '<table class="games-table">';
        html += '<thead><tr><th>Player</th><th>Date</th><th>Score</th><th>Turns</th><th>Dumplog</th></tr></thead>';
        html += '<tbody>';
        games.male_ascensions.forEach(function(game) {
          html += '<tr>';
          html += '<td>' + game.player__name + '</td>';
          html += '<td>' + (game.endtime || '') + '</td>';
          html += '<td>' + (game.points || 0).toLocaleString() + '</td>';
          html += '<td>' + (game.turns || 0).toLocaleString() + '</td>';
          html += '<td><a href="' + game.dumplog + '" target="_blank">View</a></td>';
          html += '</tr>';
        });
        html += '</tbody></table>';
      }

      // Female ascensions section
      if (games.female_ascensions && games.female_ascensions.length > 0) {
        html += '<h4><span class="progress-symbols"><span class="sym-female">♀</span></span> Female Ascensions (' + games.female_ascensions.length + ')</h4>';
        html += '<table class="games-table">';
        html += '<thead><tr><th>Player</th><th>Date</th><th>Score</th><th>Turns</th><th>Dumplog</th></tr></thead>';
        html += '<tbody>';
        games.female_ascensions.forEach(function(game) {
          html += '<tr>';
          html += '<td>' + game.player__name + '</td>';
          html += '<td>' + (game.endtime || '') + '</td>';
          html += '<td>' + (game.points || 0).toLocaleString() + '</td>';
          html += '<td>' + (game.turns || 0).toLocaleString() + '</td>';
          html += '<td><a href="' + game.dumplog + '" target="_blank">View</a></td>';
          html += '</tr>';
        });
        html += '</tbody></table>';
      }

      // No games found
      if (html === '') {
        html = '<p class="no-games-msg">No games found for this combination.</p>';
      }

      modalGames.innerHTML = html;
    }
  });
})();
