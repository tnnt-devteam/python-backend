/**
 * Clan Management Confirmation Dialogs
 * Adds "are you sure?" prompts for destructive clan actions
 */

document.addEventListener('DOMContentLoaded', function() {
  // Add confirmation for all forms with destructive actions
  var forms = document.querySelectorAll('form');

  forms.forEach(function(form) {
    form.addEventListener('submit', function(e) {
      var submitter = e.submitter;
      if (!submitter) return;

      var buttonName = submitter.getAttribute('name');
      var confirmMessage = null;

      // Determine which action is being performed
      if (buttonName === 'leave') {
        confirmMessage = 'Are you sure you want to leave this clan?';
      } else if (buttonName === 'disband') {
        confirmMessage = 'Are you sure you want to disband this clan? This cannot be undone!';
      } else if (buttonName === 'kick') {
        confirmMessage = 'Are you sure you want to kick this player from the clan?';
      } else if (buttonName === 'rescind') {
        confirmMessage = 'Are you sure you want to rescind this invitation?';
      }

      // If we need confirmation and user cancels, prevent form submission
      if (confirmMessage && !confirm(confirmMessage)) {
        e.preventDefault();
        return false;
      }
    });
  });
});
