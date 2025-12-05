// Intelligent tooltip positioning to prevent off-screen tooltips
document.addEventListener('DOMContentLoaded', function() {
    const tooltipContainers = document.querySelectorAll('.ach-hoverable');

    tooltipContainers.forEach(container => {
        container.addEventListener('mouseenter', function() {
            const tooltip = this.querySelector('.ach-tooltip');
            if (!tooltip) return;

            // Get the bounding rectangles
            const rect = tooltip.getBoundingClientRect();
            const containerRect = this.getBoundingClientRect();

            // Check if tooltip goes off the top of the viewport
            if (rect.top < 0) {
                // Position tooltip below instead
                tooltip.classList.add('tooltip-below');
            } else {
                // Remove the below class if it was previously added
                tooltip.classList.remove('tooltip-below');
            }
        });
    });
});
