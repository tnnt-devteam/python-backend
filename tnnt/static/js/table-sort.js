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
                const rows = Array.from(tbody.querySelectorAll('tr'));

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
                rows.sort((a, b) => {
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

                    // Try to parse as numbers
                    const aNum = parseFloat(aVal.replace(/,/g, ''));
                    const bNum = parseFloat(bVal.replace(/,/g, ''));

                    if (!isNaN(aNum) && !isNaN(bNum)) {
                        // Numeric comparison
                        return direction * (aNum - bNum);
                    }

                    // Check if dates (multiple formats)
                    // Format 1: "Nov 14, 09:32:14"
                    const datePattern1 = /^[A-Za-z]{3} \d{1,2}, \d{2}:\d{2}:\d{2}$/;
                    // Format 2: ISO-like "2024-11-01 23:19:19+00:00" or "2024-11-01 23:19:19"
                    const datePattern2 = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/;
                    // Format 3: Django default "Nov. 1, 2024, 11:19 p.m." or "Nov. 10, 2024, 3:41 a.m." or "Nov. 8, 2024, midnight"
                    const datePattern3 = /^[A-Za-z]{3}\. \d{1,2}, \d{4}, (\d{1,2}:\d{2} [ap]\.m\.|midnight|noon)$/;

                    if (datePattern1.test(aVal) && datePattern1.test(bVal)) {
                        // Parse dates - add current year for comparison
                        const currentYear = new Date().getFullYear();
                        const aDate = new Date(aVal + ' ' + currentYear);
                        const bDate = new Date(bVal + ' ' + currentYear);
                        return direction * (aDate - bDate);
                    } else if (datePattern2.test(aVal) && datePattern2.test(bVal)) {
                        // Parse ISO-like dates
                        const aDate = new Date(aVal.replace('+00:00', 'Z'));
                        const bDate = new Date(bVal.replace('+00:00', 'Z'));
                        return direction * (aDate - bDate);
                    } else if (datePattern3.test(aVal) && datePattern3.test(bVal)) {
                        // Parse Django formatted dates
                        // Convert "Nov. 1, 2024, 11:19 p.m." to parseable format
                        const parseDate = (str) => {
                            // Handle special cases first
                            if (str.includes('midnight')) {
                                str = str.replace('midnight', '12:00 am');
                            } else if (str.includes('noon')) {
                                str = str.replace('noon', '12:00 pm');
                            }
                            // Remove dots from month abbreviation and am/pm
                            str = str.replace(/\./g, '');
                            // JavaScript's Date constructor can parse "Nov 1, 2024, 11:19 pm"
                            return new Date(str);
                        };
                        const aDate = parseDate(aVal);
                        const bDate = parseDate(bVal);
                        return direction * (aDate - bDate);
                    }

                    // String comparison (case-insensitive)
                    return direction * aVal.toLowerCase().localeCompare(bVal.toLowerCase());
                });

                // Re-append sorted rows
                rows.forEach(row => tbody.appendChild(row));
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