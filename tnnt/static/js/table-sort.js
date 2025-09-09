// Simple table sorting functionality
document.addEventListener('DOMContentLoaded', function() {
    // Find all tables with class 'sortable'
    const tables = document.querySelectorAll('table.sortable');

    tables.forEach(table => {
        const headers = table.querySelectorAll('thead th');
        const tbody = table.querySelector('tbody');

        // Add click handlers to each header
        headers.forEach((header, index) => {
            header.style.cursor = 'pointer';
            header.setAttribute('title', 'Click to sort');

            // Add visual indicator for sortable columns
            const indicator = document.createElement('span');
            indicator.className = 'sort-indicator';
            indicator.textContent = ' ↕';
            indicator.style.opacity = '0.3';
            header.appendChild(indicator);

            // Track sort direction for each column
            header.sortDirection = 0; // 0 = unsorted, 1 = asc, -1 = desc

            header.addEventListener('click', () => {
                // Get all rows
                let rows = Array.from(tbody.querySelectorAll('tr'));

                // Determine sort direction
                let direction = header.sortDirection === 1 ? -1 : 1;

                // Reset all other headers
                headers.forEach(h => {
                    if (h !== header) {
                        h.sortDirection = 0;
                        const ind = h.querySelector('.sort-indicator');
                        if (ind) {
                            ind.textContent = ' ↕';
                            ind.style.opacity = '0.3';
                        }
                    }
                });

                // Update current header
                header.sortDirection = direction;
                indicator.textContent = direction === 1 ? ' ↑' : ' ↓';
                indicator.style.opacity = '1';

                // Sort rows
                const sortedRows = rows.slice().sort((a, b) => {
                    const aCell = a.cells[index];
                    const bCell = b.cells[index];

                    if (!aCell || !bCell) return 0;

                    let aVal = aCell.textContent.trim();
                    let bVal = bCell.textContent.trim();

                    // Check if it's a duration (format: "23:44:17" or "24 days, 12:18:54" or "1 day, 2:21:19")
                    const durationPattern1 = /^(\d+):(\d{2}):(\d{2})$/; // HH:MM:SS
                    const durationPattern2 = /^(\d+) days?, (\d+):(\d{2}):(\d{2})$/; // N day(s), HH:MM:SS

                    const parseDuration = (str) => {
                        let match;
                        if ((match = durationPattern2.exec(str))) {
                            // Days + time format
                            const days = parseInt(match[1]);
                            const hours = parseInt(match[2]);
                            const minutes = parseInt(match[3]);
                            const seconds = parseInt(match[4]);
                            return days * 86400 + hours * 3600 + minutes * 60 + seconds;
                        } else if ((match = durationPattern1.exec(str))) {
                            // Time only format
                            const hours = parseInt(match[1]);
                            const minutes = parseInt(match[2]);
                            const seconds = parseInt(match[3]);
                            return hours * 3600 + minutes * 60 + seconds;
                        }
                        return null;
                    };

                    const aDuration = parseDuration(aVal);
                    const bDuration = parseDuration(bVal);

                    if (aDuration !== null && bDuration !== null) {
                        // Duration comparison (in seconds)
                        return direction * (aDuration - bDuration);
                    }

                    // Check if it looks like an ISO date (YYYY-MM-DD HH:MM format)
                    // This MUST come before number parsing since dates start with numbers!
                    if (aVal.match(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/) &&
                        bVal.match(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/)) {
                        // ISO dates sort correctly as strings!
                        return direction * aVal.localeCompare(bVal);
                    }

                    // Try to parse as numbers
                    const aNum = parseFloat(aVal.replace(/,/g, ''));
                    const bNum = parseFloat(bVal.replace(/,/g, ''));

                    if (!isNaN(aNum) && !isNaN(bNum)) {
                        // Numeric comparison
                        return direction * (aNum - bNum);
                    }

                    // String comparison (case-insensitive)
                    return direction * aVal.toLowerCase().localeCompare(bVal.toLowerCase());
                });

                // Clear the tbody and re-append sorted rows
                while (tbody.firstChild) {
                    tbody.removeChild(tbody.firstChild);
                }

                // Now append the sorted rows
                sortedRows.forEach(row => {
                    tbody.appendChild(row);
                });
            });
        });

        // Set initial sort indicator for first column if it's the default sort
        if (headers.length > 0 && table.classList.contains('default-sort-first')) {
            const firstHeader = headers[0];
            firstHeader.sortDirection = 1;
            const indicator = firstHeader.querySelector('.sort-indicator');
            if (indicator) {
                indicator.textContent = ' ↑';
                indicator.style.opacity = '1';
            }
        }
    });
});