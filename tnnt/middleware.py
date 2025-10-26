"""
Middleware for admin functionality
"""

from django.shortcuts import redirect
from django.contrib.auth import logout
from tnnt import admin_utils
import logging

logger = logging.getLogger(__name__)

class LoginControlMiddleware:
    """
    Middleware to enforce login control settings.

    If non-admin logins are disabled, this middleware will log out
    any non-admin users and redirect them to the logins disabled page.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Check if user is authenticated and not an admin
        if request.user.is_authenticated and not admin_utils.is_admin(request.user):
            # Check if logins are allowed
            if not admin_utils.check_login_allowed(request.user):
                logger.info(
                    'Logging out %s due to login control',
                    request.user.username
                )
                logout(request)
                return redirect('/logins-disabled')

        response = self.get_response(request)
        return response
