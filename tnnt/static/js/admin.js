// Admin Panel JavaScript - CSP compliant (no inline scripts)

document.addEventListener('DOMContentLoaded', function() {
    // Handle login toggle confirmation
    const loginForm = document.querySelector('form[name="login-toggle-form"]');
    if (loginForm) {
        loginForm.addEventListener('submit', function(e) {
            const action = this.dataset.action;
            const message = `Are you sure you want to ${action} non-admin logins?`;
            if (!confirm(message)) {
                e.preventDefault();
            }
        });
    }

    // Handle clan operations toggle confirmation
    const clanForm = document.querySelector('form[name="clan-toggle-form"]');
    if (clanForm) {
        clanForm.addEventListener('submit', function(e) {
            const action = this.dataset.action;
            const message = `Are you sure you want to ${action} clan operations?`;
            if (!confirm(message)) {
                e.preventDefault();
            }
        });
    }
});
