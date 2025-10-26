"""
Helper functions for admin functionality
"""

from tnnt import settings
from scoreboard.models import SiteSettings
import logging

logger = logging.getLogger(__name__)

def is_admin(user):
    """
    Check if a user is a site administrator.

    Args:
        user: Django User object

    Returns:
        bool: True if user is in SITE_ADMINS list, False otherwise
    """
    if not user or not user.is_authenticated:
        return False
    return user.username in settings.SITE_ADMINS

def get_site_settings():
    """
    Get or create the SiteSettings singleton instance.

    Returns:
        SiteSettings: The singleton SiteSettings object
    """
    return SiteSettings.load()

def check_login_allowed(user):
    """
    Check if a user is allowed to be logged in.

    Admins are always allowed. Non-admins are only allowed if
    login_enabled is True in SiteSettings.

    Args:
        user: Django User object

    Returns:
        bool: True if user is allowed to be logged in
    """
    if not user or not user.is_authenticated:
        return False

    # Admins are always allowed
    if is_admin(user):
        return True

    # Check if non-admin logins are enabled
    site_settings = get_site_settings()
    return site_settings.login_enabled

def check_clan_operations_allowed(user):
    """
    Check if clan operations are allowed for a user.

    Admins can always perform clan operations. Non-admins can only
    perform clan operations if clan_operations_enabled is True.

    Args:
        user: Django User object

    Returns:
        bool: True if clan operations are allowed
    """
    if not user or not user.is_authenticated:
        return False

    # Admins are always allowed
    if is_admin(user):
        return True

    # Check if clan operations are enabled
    site_settings = get_site_settings()
    return site_settings.clan_operations_enabled
