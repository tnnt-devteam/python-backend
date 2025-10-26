"""
Context processors to add variables to all templates
"""

from tnnt import admin_utils

def admin_status(request):
    """
    Add is_admin variable to all template contexts
    """
    return {
        'is_admin': admin_utils.is_admin(request.user) if request.user else False
    }
