document.addEventListener("DOMContentLoaded", function(event) {
    // set up event listener for showing or hiding the achievements tables
    // (one per category, with the category links above them)
    var hider = document.getElementById('ach-hide');
    hider.addEventListener('click', function(event) {
        var sections = document.getElementById('ach-sections');
        var hider = document.getElementById('ach-hide');
        if (sections.style.display === 'none') {
            sections.style.display = '';
            hider.textContent = '[hide tables]';
        }
        else {
            sections.style.display = 'none';
            hider.textContent = '[show tables]';
        }
    });

    // Set up achievement filtering
    var filters = document.querySelectorAll('.ach-filter');
    filters.forEach(function(filter) {
        filter.addEventListener('click', function() {
            // Remove active class from all filters
            filters.forEach(function(f) {
                f.classList.remove('active');
            });

            // Add active class to clicked filter
            this.classList.add('active');

            // Get the filter type from ID
            var filterId = this.id;
            var filterType = filterId.replace('ach-filter-', '');

            // Get all achievement rows
            var rows = document.querySelectorAll('.ach-section tbody tr');

            // Show/hide rows based on filter
            rows.forEach(function(row) {
                var status = row.getAttribute('data-status');

                if (filterType === 'all') {
                    row.style.display = '';
                } else if (filterType === 'achieved' && status === 'achieved') {
                    row.style.display = '';
                } else if (filterType === 'temp' && status === 'temp') {
                    row.style.display = '';
                } else if (filterType === 'not' && status === 'not') {
                    row.style.display = '';
                } else {
                    row.style.display = 'none';
                }
            });

            // Hide the categories with no rows left, and their links
            document.querySelectorAll('.ach-section').forEach(function(section) {
                var shown = Array.from(section.querySelectorAll('tbody tr'))
                    .some(function(row) { return row.style.display !== 'none'; });
                var display = shown ? '' : 'none';
                section.style.display = display;
                var link = document.querySelector(
                    'nav.ach-categories li[data-section="' + section.dataset.section + '"]');
                if (link) {
                    link.style.display = display;
                }
            });
        });
    });

    // Set achievement progress bar width from data attribute
    var progressBar = document.querySelector('.achieve-bar');
    if (progressBar) {
        var progress = progressBar.getAttribute('data-progress');
        if (progress) {
            progressBar.style.width = progress + '%';
        }
    }
});
