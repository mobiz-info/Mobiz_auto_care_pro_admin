"""
Canonical Permission Registry & Helpers for Designation-based Access Control.
Used across Web Admin (templates & views) and Mobile APIs.
"""

PERMISSION_MENU_SCHEMA = [
    {
        'key': 'new_job',
        'label': 'New Job',
        'icon': 'ph-plus-circle',
        'actions': [
            {'key': 'view', 'label': 'Access New Job'},
            {'key': 'create_customer', 'label': 'Add Customer'},
            {'key': 'add_vehicle', 'label': 'Add Vehicle'},
            {'key': 'create_invoice', 'label': 'Create Invoice'},
        ],
    },
    {
        'key': 'quick_sale',
        'label': 'Quick Sale',
        'icon': 'ph-lightning',
        'actions': [
            {'key': 'view', 'label': 'Access Quick Sale'},
            {'key': 'create', 'label': 'Create Quick Sale Invoice'},
        ],
    },
    {
        'key': 'job_card',
        'label': 'Job Card',
        'icon': 'ph-clipboard-text',
        'actions': [
            {'key': 'view', 'label': 'View Job Cards'},
            {'key': 'create', 'label': 'Create Job Card'},
            {'key': 'edit', 'label': 'Edit / Update Stage'},
            {'key': 'delete', 'label': 'Delete Job Card'},
        ],
    },
    {
        'key': 'leads',
        'label': 'Leads',
        'icon': 'ph-funnel',
        'actions': [
            {'key': 'view', 'label': 'View Leads'},
            {'key': 'create', 'label': 'Create Lead'},
            {'key': 'edit', 'label': 'Edit / Update Lead'},
            {'key': 'delete', 'label': 'Delete Lead'},
        ],
    },
    {
        'key': 'quotations',
        'label': 'Quotations',
        'icon': 'ph-file-text',
        'actions': [
            {'key': 'view', 'label': 'View Quotations'},
            {'key': 'create', 'label': 'Create Quotation'},
            {'key': 'edit', 'label': 'Edit Quotation'},
            {'key': 'delete', 'label': 'Delete Quotation'},
            {'key': 'convert', 'label': 'Convert to Job Card / Invoice'},
        ],
    },
    {
        'key': 'bookings',
        'label': 'Bookings & Book Now',
        'icon': 'ph-calendar-check',
        'actions': [
            {'key': 'view', 'label': 'View Bookings'},
            {'key': 'create', 'label': 'Create Booking'},
            {'key': 'edit', 'label': 'Edit / Update Status'},
            {'key': 'delete', 'label': 'Delete Booking'},
        ],
    },
    {
        'key': 'bill',
        'label': 'Bill (Invoices)',
        'icon': 'ph-receipt',
        'actions': [
            {'key': 'view', 'label': 'View Bills / Invoices'},
            {'key': 'create', 'label': 'Create Invoice'},
            {'key': 'edit', 'label': 'Edit Invoice'},
            {'key': 'delete', 'label': 'Delete Invoice'},
            {'key': 'pdf', 'label': 'Print / Download PDF'},
            {'key': 'whatsapp', 'label': 'Share via WhatsApp'},
        ],
    },
    {
        'key': 'outstanding',
        'label': 'Outstanding / Collection',
        'icon': 'ph-hand-coins',
        'actions': [
            {'key': 'view', 'label': 'View Outstanding'},
            {'key': 'collect', 'label': 'Collect Payment'},
        ],
    },
    {
        'key': 'receipt',
        'label': 'Receipts',
        'icon': 'ph-scroll',
        'actions': [
            {'key': 'view', 'label': 'View Receipts'},
            {'key': 'create', 'label': 'Create Receipt'},
            {'key': 'delete', 'label': 'Delete Receipt'},
        ],
    },
    {
        'key': 'customers',
        'label': 'Customers & Vehicles',
        'icon': 'ph-users',
        'actions': [
            {'key': 'view', 'label': 'View Customers & Vehicles'},
            {'key': 'create', 'label': 'Add Customer / Vehicle'},
            {'key': 'edit', 'label': 'Edit Customer / Vehicle'},
            {'key': 'delete', 'label': 'Delete Customer / Vehicle'},
        ],
    },
    {
        'key': 'reports',
        'label': 'Reports',
        'icon': 'ph-chart-bar',
        'actions': [
            {'key': 'view', 'label': 'View Reports'},
        ],
    },
    {
        'key': 'schemes',
        'label': 'Schemes',
        'icon': 'ph-gift',
        'actions': [
            {'key': 'view', 'label': 'View Schemes'},
            {'key': 'create', 'label': 'Create Scheme'},
            {'key': 'edit', 'label': 'Edit Scheme'},
            {'key': 'delete', 'label': 'Delete Scheme'},
        ],
    },
    {
        'key': 'expense',
        'label': 'Expense',
        'icon': 'ph-currency-circle-dollar',
        'actions': [
            {'key': 'view', 'label': 'View Expenses'},
            {'key': 'create', 'label': 'Add Expense'},
            {'key': 'edit', 'label': 'Edit Expense'},
            {'key': 'delete', 'label': 'Delete Expense'},
        ],
    },
    {
        'key': 'suppliers',
        'label': 'Suppliers & Payables',
        'icon': 'ph-truck',
        'actions': [
            {'key': 'view', 'label': 'View Suppliers & Payables'},
            {'key': 'create', 'label': 'Add Supplier'},
            {'key': 'edit', 'label': 'Edit Supplier'},
            {'key': 'pay', 'label': 'Make Supplier Payment'},
        ],
    },
    {
        'key': 'purchase',
        'label': 'Purchase & Requests',
        'icon': 'ph-shopping-cart',
        'actions': [
            {'key': 'view', 'label': 'View Purchases'},
            {'key': 'create', 'label': 'Create Purchase Entry / Req'},
            {'key': 'edit', 'label': 'Edit / Approve'},
        ],
    },
    {
        'key': 'stock',
        'label': 'Stock & Inventory',
        'icon': 'ph-package',
        'actions': [
            {'key': 'view', 'label': 'View Stock'},
            {'key': 'create', 'label': 'Add Stock Item'},
            {'key': 'edit', 'label': 'Edit Stock'},
            {'key': 'delete', 'label': 'Delete Stock'},
        ],
    },
    {
        'key': 'staff_payslips',
        'label': 'Payslips & Staff Leaves',
        'icon': 'ph-identification-badge',
        'actions': [
            {'key': 'view', 'label': 'View Own Payslips & Leaves'},
            {'key': 'apply_leave', 'label': 'Apply for Leave'},
        ],
    },
    {
        'key': 'notifications',
        'label': 'Notifications / Broadcast',
        'icon': 'ph-megaphone',
        'actions': [
            {'key': 'view', 'label': 'View Notifications'},
            {'key': 'send', 'label': 'Send Broadcast'},
        ],
    },
    {
        'key': 'complaints',
        'label': 'Complaints',
        'icon': 'ph-warning-circle',
        'actions': [
            {'key': 'view', 'label': 'View Complaints'},
            {'key': 'resolve', 'label': 'Resolve / Update'},
        ],
    },
    {
        'key': 'settings',
        'label': 'Settings & Masters',
        'icon': 'ph-gear',
        'actions': [
            {'key': 'view', 'label': 'View Settings / Masters'},
            {'key': 'edit', 'label': 'Edit Settings'},
        ],
    },
]


def get_full_permissions():
    """Return a permissions dict with every menu and action enabled."""
    perms = {}
    for menu in PERMISSION_MENU_SCHEMA:
        perms[menu['key']] = {act['key']: True for act in menu['actions']}
    return perms


def get_empty_permissions():
    """Return a permissions dict with every menu and action disabled."""
    perms = {}
    for menu in PERMISSION_MENU_SCHEMA:
        perms[menu['key']] = {act['key']: False for act in menu['actions']}
    return perms


def get_default_permissions_for_code(code):
    """Sensible defaults for legacy hardcoded designations."""
    code = (code or '').upper().strip()
    if code == 'BRANCH_MANAGER':
        return get_full_permissions()

    perms = get_empty_permissions()
    if code == 'CLERICAL':
        for key in ['new_job', 'quick_sale', 'job_card', 'bookings', 'bill', 'outstanding', 'receipt', 'customers', 'expense', 'staff_payslips']:
            if key in perms:
                perms[key] = {k: True for k in perms[key]}
        if 'bill' in perms:
            perms['bill']['delete'] = False
    elif code == 'MARKETING':
        for key in ['leads', 'quotations', 'bookings', 'customers', 'staff_payslips', 'notifications']:
            if key in perms:
                perms[key] = {k: True for k in perms[key]}
    elif code == 'SERVICE':
        for key in ['job_card', 'bookings', 'staff_payslips']:
            if key in perms:
                perms[key] = {k: True for k in perms[key]}
        if 'job_card' in perms:
            perms['job_card']['delete'] = False
    return perms


def get_user_permissions(user):
    """
    Resolve effective permissions for any authenticated user.
    - SUPER_ADMIN, COMPANY_ADMIN, BRANCH_ADMIN: full access (is_full_access=True).
    - STAFF (linked via user.staff_profile): resolved from staff.designation_obj.permissions.
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return {'is_full_access': False, 'designation_name': '', 'permissions': get_empty_permissions()}

    if getattr(user, 'is_superuser', False):
        return {'is_full_access': True, 'designation_name': 'Super Admin', 'permissions': get_full_permissions()}

    role_name = ''
    if hasattr(user, 'profile') and user.profile and user.profile.role:
        role_name = (user.profile.role.name or '').upper().strip()

    if role_name in ('SUPER_ADMIN', 'COMPANY_ADMIN', 'BRANCH_ADMIN'):
        return {'is_full_access': True, 'designation_name': role_name, 'permissions': get_full_permissions()}

    staff = getattr(user, 'staff_profile', None)
    if staff and not getattr(staff, 'is_deleted', False):
        desig = getattr(staff, 'designation_obj', None)
        if desig and not getattr(desig, 'is_deleted', False):
            # Merge with empty permissions so any newly added menus default safely to False
            resolved = get_empty_permissions()
            raw = desig.permissions or {}
            for m_key, actions_dict in resolved.items():
                if isinstance(raw.get(m_key), dict):
                    for a_key in actions_dict:
                        actions_dict[a_key] = bool(raw[m_key].get(a_key, False))
            return {
                'is_full_access': False,
                'designation_id': str(desig.id),
                'designation_name': desig.name,
                'permissions': resolved,
            }
        # Fallback to legacy designation CharField
        return {
            'is_full_access': False,
            'designation_id': None,
            'designation_name': staff.get_designation_display() if hasattr(staff, 'get_designation_display') else (staff.designation or ''),
            'permissions': get_default_permissions_for_code(staff.designation),
        }

    # Unknown or non-staff user without admin role
    return {'is_full_access': False, 'designation_name': role_name, 'permissions': get_empty_permissions()}


def user_has_permission(user, menu_key, action='view'):
    """Check if user has permission for a specific menu & action."""
    info = get_user_permissions(user)
    if info['is_full_access']:
        return True
    return bool(info['permissions'].get(menu_key, {}).get(action, False))

