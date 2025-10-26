document.addEventListener("DOMContentLoaded", function(event) {
    // set up event listener for showing or hiding the achievements table
    var hider = document.getElementById('ach-hide');
    hider.addEventListener('click', function(event) {
        var table = document.getElementById('achievements-table');
        var hider = document.getElementById('ach-hide');
        if (table.style.display === 'none') {
            table.style.display = 'block';
            hider.textContent = '[hide table]';
        }
        else {
            table.style.display = 'none';
            hider.textContent = '[show table]';
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
            var rows = document.querySelectorAll('#achievements-table tbody tr');

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
