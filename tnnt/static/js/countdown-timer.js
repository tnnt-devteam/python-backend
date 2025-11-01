// Countdown timer for clan freeze time
(function() {
    function updateCountdown() {
        const countdownElements = document.querySelectorAll(
            '.freeze-countdown'
        );

        countdownElements.forEach(function(element) {
            const freezeTime = new Date(
                element.getAttribute('data-freeze-time')
            );
            const now = new Date();
            const timeRemaining = freezeTime - now;

            if (timeRemaining <= 0) {
                element.textContent = 'Clan freeze is now in effect!';
                element.style.color = '#eb0';
                element.style.fontWeight = 'bold';
                return;
            }

            const days = Math.floor(timeRemaining / (1000 * 60 * 60 * 24));
            const hours = Math.floor(
                (timeRemaining % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60)
            );
            const minutes = Math.floor(
                (timeRemaining % (1000 * 60 * 60)) / (1000 * 60)
            );
            const seconds = Math.floor(
                (timeRemaining % (1000 * 60)) / 1000
            );

            let countdownText = '';
            if (days > 0) {
                countdownText += days + ' day' + (days !== 1 ? 's' : '') +
                                 ', ';
            }
            countdownText += hours + ' hour' + (hours !== 1 ? 's' : '') +
                             ', ';
            countdownText += minutes + ' minute' +
                             (minutes !== 1 ? 's' : '') + ', ';
            countdownText += seconds + ' second' +
                             (seconds !== 1 ? 's' : '');

            element.textContent = countdownText;
        });
    }

    // Update immediately on load
    updateCountdown();

    // Update every second
    setInterval(updateCountdown, 1000);
})();
