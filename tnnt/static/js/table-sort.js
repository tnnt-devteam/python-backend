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
                    
                    // Try to parse as numbers first
                    const aNum = parseFloat(aVal.replace(/,/g, ''));
                    const bNum = parseFloat(bVal.replace(/,/g, ''));
                    
                    if (!isNaN(aNum) && !isNaN(bNum)) {
                        // Numeric comparison
                        return direction * (aNum - bNum);
                    }
                    
                    // Check if dates (format: "Nov 14, 09:32:14")
                    const datePattern = /^[A-Za-z]{3} \d{1,2}, \d{2}:\d{2}:\d{2}$/;
                    if (datePattern.test(aVal) && datePattern.test(bVal)) {
                        // Parse dates - add current year for comparison
                        const currentYear = new Date().getFullYear();
                        const aDate = new Date(aVal + ' ' + currentYear);
                        const bDate = new Date(bVal + ' ' + currentYear);
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