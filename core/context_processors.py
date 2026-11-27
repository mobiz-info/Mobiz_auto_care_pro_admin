from client_management.permissions import get_user_permissions


def user_permissions_context(request):
    if hasattr(request, 'user') and request.user.is_authenticated:
        info = get_user_permissions(request.user)
        return {
            'is_full_access': info.get('is_full_access', False),
            'user_perms': info.get('permissions', {}),
            'user_designation_name': info.get('designation_name', ''),
        }
    return {
        'is_full_access': False,
        'user_perms': {},
        'user_designation_name': '',
    }
