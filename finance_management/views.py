from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Q, Sum, F, DecimalField, ExpressionWrapper
from django.views.decorators.csrf import csrf_exempt
from decimal import Decimal
from django.core.paginator import Paginator
from datetime import datetime
from django.utils import timezone
from django.db.models import DecimalField, Value
from django.db.models.functions import Coalesce, TruncDate
from django.template.loader import render_to_string
from django.http import HttpResponse

import sys
import os
# Ensure macOS Homebrew libraries (like libgobject for WeasyPrint) are searchable
if sys.platform == 'darwin':
    os.environ['DYLD_FALLBACK_LIBRARY_PATH'] = '/opt/homebrew/lib:' + os.environ.get('DYLD_FALLBACK_LIBRARY_PATH', '')

from weasyprint import HTML


from core.functions import get_auto_id, log_activity
from client_management.api_views import get_user_from_token
from .models import Invoice, Receipt, InvoiceItem, BranchInvoiceCustomisation
from booking_management.models import Booking
from client_management.models import Branch
from service_management.models import ServiceType
from master.models import ExpenseEntry, ExpenseHead


@login_required
def invoice_list(request):
    user = request.user
    role = user.profile.role.name if hasattr(user, 'profile') and user.profile.role else None

    today = timezone.localdate() if hasattr(timezone, 'localdate') else timezone.now().date()
    today_str = today.strftime('%Y-%m-%d')

    from_date_param = request.GET.get('from_date') if 'from_date' in request.GET else request.GET.get('fromdate')
    to_date_param = request.GET.get('to_date') if 'to_date' in request.GET else request.GET.get('todate')

    if from_date_param is None:
        from_date = today_str
    else:
        from_date = from_date_param.strip()

    if to_date_param is None:
        to_date = today_str
    else:
        to_date = to_date_param.strip()

    invoices = Invoice.objects.filter(is_deleted=False).select_related(
        'customer', 'vehicle', 'vehicle__vehicle_type_model', 'branch'
    ).prefetch_related('items').order_by('-date', '-auto_id')

    branches = None
    if role == 'COMPANY_ADMIN' and hasattr(user.profile, 'company') and user.profile.company:
        invoices = invoices.filter(branch__company=user.profile.company)
        branches = Branch.objects.filter(company=user.profile.company, is_deleted=False)
    elif role == 'BRANCH_ADMIN' and hasattr(user, 'managed_branch'):
        invoices = invoices.filter(branch=user.managed_branch)

    branch_id = request.GET.get('branch_id') or request.GET.get('branch')
    if branch_id:
        invoices = invoices.filter(branch_id=branch_id)

    # Filter by date range (defaults to today)
    if from_date:
        try:
            parsed_from = datetime.strptime(from_date, '%Y-%m-%d').date()
            invoices = invoices.filter(date__gte=parsed_from)
        except ValueError:
            invoices = invoices.filter(date__gte=from_date)

    if to_date:
        try:
            parsed_to = datetime.strptime(to_date, '%Y-%m-%d').date()
            invoices = invoices.filter(date__lte=parsed_to)
        except ValueError:
            invoices = invoices.filter(date__lte=to_date)

    search = request.GET.get('search', '').strip()
    if search:
        invoices = invoices.filter(
            Q(invoice_number__icontains=search) |
            Q(customer__name__icontains=search) |
            Q(customer__phone__icontains=search) |
            Q(vehicle__vehicle_number__icontains=search)
        )

    payment_mode = request.GET.get('payment_mode', '').strip()
    if payment_mode:
        invoices = invoices.filter(receipts__payment_mode=payment_mode).distinct()

    totals = invoices.aggregate(
        total_subtotal=Sum('subtotal'),
        total_discount=Sum('discount'),
        total_tax=Sum('tax_amount'),
        total_total=Sum('total'),
        total_collected=Sum('amount_collected')
    )
    for key in totals:
        if totals[key] is None:
            totals[key] = Decimal('0.00')

    return render(request, 'invoice/list.html', {
        'invoices': invoices,
        'search': search,
        'payment_mode': payment_mode,
        'from_date': from_date,
        'to_date': to_date,
        'branch_id': branch_id,
        'branches': branches,
        'title': 'Invoices',
        'totals': totals
    })


@login_required
def outstanding_list(request):
    """Show all invoices where amount_collected < total (customer has balance due) with date & branch filtering."""
    user = request.user
    role = user.profile.role.name if hasattr(user, 'profile') and user.profile.role else None

    company = None
    branch = None
    branches = None

    if role == 'COMPANY_ADMIN':
        company = getattr(getattr(user, 'profile', None), 'company', None)
        if company:
            branches = Branch.objects.filter(company=company, is_deleted=False).order_by('name')
    else:
        branch = getattr(user, 'managed_branch', None)
        if not branch and hasattr(user, 'profile') and user.profile.company:
            branch = Branch.objects.filter(company=user.profile.company, is_deleted=False).first()

        if branch:
            company = branch.company
        elif hasattr(user, 'profile') and user.profile.company:
            company = user.profile.company

    # Currency symbol
    currency_symbol = '₹'
    if company and getattr(company, 'country', None) and company.country.currency_symbol:
        currency_symbol = company.country.currency_symbol

    # Base query: only invoices with outstanding balance
    invoices = Invoice.objects.filter(
        is_deleted=False,
        customer__is_deleted=False,
    ).select_related(
        'customer', 'vehicle', 'vehicle__vehicle_type_model', 'branch'
    ).filter(amount_collected__lt=F('total'))

    # Scope by role and branch filter
    branch_id = request.GET.get('branch_id', '').strip()
    if role == 'COMPANY_ADMIN' and company:
        invoices = invoices.filter(branch__company=company)
        if branch_id and branch_id.lower() != 'all':
            invoices = invoices.filter(branch_id=branch_id)
    else:
        if branch:
            invoices = invoices.filter(branch=branch)
        branch_id = ''

    # Date range filters
    from_date = request.GET.get('from_date', '').strip()
    to_date = request.GET.get('to_date', '').strip()
    if from_date:
        invoices = invoices.filter(date__gte=from_date)
    if to_date:
        invoices = invoices.filter(date__lte=to_date)

    # Search
    search = request.GET.get('search', '').strip()
    if search:
        invoices = invoices.filter(
            Q(customer__name__icontains=search) |
            Q(customer__phone__icontains=search) |
            Q(customer__whatsapp_number__icontains=search) |
            Q(invoice_number__icontains=search) |
            Q(vehicle__vehicle_number__icontains=search) |
            Q(branch__name__icontains=search)
        )

    invoices = invoices.order_by('-date', '-id')

    # Data lists and KPI summaries
    invoice_list_data = []
    total_outstanding = Decimal('0.00')
    total_invoiced_value = Decimal('0.00')
    total_collected_value = Decimal('0.00')

    from collections import defaultdict
    customer_summary = defaultdict(lambda: {'customer': None, 'total_outstanding': Decimal('0'), 'total_invoiced': Decimal('0'), 'invoices': []})

    for inv in invoices:
        outstanding = inv.total - inv.amount_collected
        total_outstanding += outstanding
        total_invoiced_value += inv.total
        total_collected_value += inv.amount_collected

        progress_percent = int((inv.amount_collected / inv.total) * 100) if inv.total > 0 else 0

        item_data = {
            'invoice': inv,
            'outstanding': outstanding,
            'progress_percent': progress_percent,
        }
        invoice_list_data.append(item_data)

        cid = str(inv.customer.id)
        customer_summary[cid]['customer'] = inv.customer
        customer_summary[cid]['total_outstanding'] += outstanding
        customer_summary[cid]['total_invoiced'] += inv.total
        customer_summary[cid]['invoices'].append(item_data)

    # Pagination for invoices list
    from django.core.paginator import Paginator
    paginator = Paginator(invoice_list_data, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    view_mode = request.GET.get('view_mode', 'list')

    context = {
        'page_obj': page_obj,
        'customer_summary': list(customer_summary.values()),
        'total_outstanding': total_outstanding,
        'total_invoiced_value': total_invoiced_value,
        'total_collected_value': total_collected_value,
        'total_pending_count': len(invoice_list_data),
        'search': search,
        'from_date': from_date,
        'to_date': to_date,
        'branch_id': branch_id,
        'branches': branches,
        'branch': branch,
        'role_name': role,
        'currency_symbol': currency_symbol,
        'view_mode': view_mode,
        'title': 'Collection / Outstanding',
    }

    return render(request, 'invoice/outstanding.html', context)


@login_required
def collect_payment(request, invoice_id):
    """Collect partial or full payment for an outstanding invoice and generate receipt."""
    user = request.user
    role = user.profile.role.name if hasattr(user, 'profile') and user.profile.role else None

    invoice = get_object_or_404(Invoice, id=invoice_id, is_deleted=False)

    # Scope check
    if role == 'COMPANY_ADMIN':
        if not invoice.branch.company == user.profile.company:
            messages.error(request, "Access denied.")
            return redirect('outstanding_list')
    elif role == 'BRANCH_ADMIN':
        if invoice.branch != user.managed_branch:
            messages.error(request, "Access denied.")
            return redirect('outstanding_list')

    if request.method == 'POST':
        amount_str = request.POST.get('amount', '0').strip()
        payment_mode = request.POST.get('payment_mode', 'cash')
        remarks = request.POST.get('remarks', 'Outstanding collection')
        collection_date_str = request.POST.get('collection_date') or request.POST.get('date')
        try:
            amount = Decimal(amount_str)
            outstanding = invoice.total - invoice.amount_collected
            if amount <= 0:
                msg = "Amount must be greater than 0."
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'message': msg}, status=400)
                messages.error(request, msg)
            elif amount > outstanding:
                currency = invoice.branch.company.country.currency_symbol if invoice.branch.company.country else '₹'
                msg = f"Amount {currency}{amount} exceeds outstanding {currency}{outstanding}."
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'message': msg}, status=400)
                messages.error(request, msg)
            else:
                invoice.amount_collected += amount
                invoice.save()

                # Generate Receipt for consistent accounting
                from master.functions import get_auto_id
                from finance_management.models import Receipt
                receipt_auto_id = get_auto_id(Receipt)
                receipt = Receipt.objects.create(
                    auto_id=receipt_auto_id,
                    creator=user,
                    receipt_number=f"RCPT-{str(receipt_auto_id).zfill(5)}",
                    invoice=invoice,
                    amount=amount,
                    payment_mode=payment_mode,
                    remarks=remarks,
                )

                if collection_date_str:
                    try:
                        from datetime import datetime
                        from django.utils import timezone
                        parsed_date = datetime.strptime(str(collection_date_str).strip()[:10], '%Y-%m-%d').date()
                        dt = timezone.datetime.combine(parsed_date, timezone.localtime().time())
                        dt = timezone.make_aware(dt) if timezone.is_naive(dt) else dt
                        Receipt.objects.filter(id=receipt.id).update(created_at=dt, date_added=dt)
                    except Exception:
                        pass

                remaining = invoice.total - invoice.amount_collected
                currency = invoice.branch.company.country.currency_symbol if invoice.branch.company.country else '₹'
                if remaining == 0:
                    success_msg = f"✓ Full payment of {currency}{amount:,.2f} collected for Invoice #{invoice.invoice_number}. Fully settled."
                else:
                    success_msg = f"✓ {currency}{amount:,.2f} collected for Invoice #{invoice.invoice_number}. Remaining outstanding: {currency}{remaining:,.2f}."

                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': True,
                        'message': success_msg,
                        'new_collected': str(invoice.amount_collected),
                        'remaining': str(remaining),
                        'fully_settled': remaining == 0,
                        'receipt_number': receipt.receipt_number
                    })

                messages.success(request, success_msg)
                return redirect('outstanding_list')
        except Exception as e:
            err_msg = f"Invalid amount: {e}"
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'message': err_msg}, status=400)
            messages.error(request, err_msg)

    return redirect('outstanding_list')


def api_list_invoices(request):
    """Mobile API: list invoices with optional date filters."""
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': 'Only GET allowed'}, status=405)

    user = get_user_from_token(request)
    if not user:
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=401)

    invoices = Invoice.objects.filter(is_deleted=False).select_related(
        'customer', 'vehicle', 'vehicle__vehicle_type_model', 'branch'
    ).prefetch_related('items', 'items__service_detail', 'reminder_plans').order_by('-date', '-auto_id')

    role = user.profile.role.name if user.profile.role else None
    if role == 'BRANCH_ADMIN' and hasattr(user, 'managed_branch'):
        invoices = invoices.filter(branch=user.managed_branch)
    elif role == 'COMPANY_ADMIN' and user.profile.company:
        invoices = invoices.filter(branch__company=user.profile.company)

    invoice_id = request.GET.get('invoice_id') or request.GET.get('id')
    if invoice_id:
        invoices = invoices.filter(id=invoice_id)
    else:
        from_date = request.GET.get('from_date')
        to_date = request.GET.get('to_date')
        if from_date:
            invoices = invoices.filter(date__gte=from_date)
        if to_date:
            invoices = invoices.filter(date__lte=to_date)

    payment_mode = request.GET.get('payment_mode')
    if payment_mode:
        invoices = invoices.filter(receipts__payment_mode=payment_mode).distinct()

    search = request.GET.get('search')
    if search:
        search = search.strip()
        invoices = invoices.filter(
            Q(invoice_number__icontains=search) |
            Q(customer__name__icontains=search) |
            Q(customer__phone__icontains=search) |
            Q(vehicle__vehicle_number__icontains=search) |
            Q(vehicle__vehicle_type_model__name__icontains=search)
        )

    results = []
    for inv in invoices:
        services_data = []
        extras_data = []
        for item in inv.items.all():
            if item.stock_item:
                continue
            is_ext = False
            ext_id = None
            if hasattr(item, 'extra') and item.extra:
                is_ext = True
                ext_id = str(item.extra.id)
            elif not item.service and not item.stock_item and item.service_name:
                from client_management.models import Extra
                from django.db.models import Q
                clean_name = item.service_name.strip()
                base_name = clean_name.split('(')[0].strip()
                company_obj = inv.branch.company if inv.branch else None
                extra_match = Extra.objects.filter(
                    Q(company=company_obj) | Q(company__isnull=True),
                    name__iexact=base_name,
                    is_deleted=False
                ).first()
                if extra_match:
                    is_ext = True
                    ext_id = str(extra_match.id)

            s_item = {
                'id': ext_id if is_ext else (str(item.service.id) if item.service else str(item.id)),
                'service_id': str(item.service.id) if item.service else None,
                'extra_id': ext_id,
                'is_extra': is_ext,
                'name': item.service_name,
                'rate': str(item.rate),
                'discount': str(item.discount),
                'qty': float(item.qty) if item.qty else 1.0,
                'net_taxable_amount': str(item.net_taxable_amount) if item.net_taxable_amount else str(item.rate),
                'service_category': item.service_detail.service_category if hasattr(item, 'service_detail') and item.service_detail else '',
                'smoke_test_period_months': item.service_detail.smoke_test_period_months if hasattr(item, 'service_detail') and item.service_detail else None,
                'warranty_value': item.service_detail.warranty_value if hasattr(item, 'service_detail') and item.service_detail else None,
                'warranty_unit': item.service_detail.warranty_unit if hasattr(item, 'service_detail') and item.service_detail else None,
                'service_detail': {
                    'service_category': item.service_detail.service_category,
                    'smoke_test_period_months': item.service_detail.smoke_test_period_months,
                    'warranty_value': item.service_detail.warranty_value,
                    'warranty_unit': item.service_detail.warranty_unit,
                    'odometer_at_service': item.service_detail.odometer_at_service,
                    'next_oil_change_km': item.service_detail.next_oil_change_km,
                    'next_tyre_change_km': item.service_detail.next_tyre_change_km,
                    'next_alignment_km': item.service_detail.next_alignment_km,
                    'alignment_done': item.service_detail.alignment_done,
                    'balancing_done': item.service_detail.balancing_done,
                    'alignment_notes': item.service_detail.alignment_notes,
                } if hasattr(item, 'service_detail') and item.service_detail else None,
            }
            services_data.append(s_item)
            if is_ext:
                extras_data.append(s_item)

        reminders_data = []
        custom_reminders_data = []
        try:
            sorted_plans = sorted(
                [rp for rp in inv.reminder_plans.all() if not rp.is_deleted],
                key=lambda x: (x.reminder_no, x.scheduled_date or datetime.min.date())
            )
            for rp in sorted_plans:
                days_after = (rp.scheduled_date - inv.date).days if (rp.scheduled_date and inv.date) else 0
                is_custom = (rp.template_name or '') not in ('insurancereminder', 'smoketest')
                rem_dict = {
                    'id': str(rp.id),
                    'days_after': days_after,
                    'days': days_after,
                    'scheduled_date': str(rp.scheduled_date) if rp.scheduled_date else '',
                    'template_name': rp.template_name or '',
                    'reminder_no': rp.reminder_no,
                    'is_sent': rp.is_sent,
                    'is_custom': is_custom,
                }
                reminders_data.append(rem_dict)
                if is_custom:
                    custom_reminders_data.append(rem_dict)
        except Exception:
            pass

        results.append({
            'id': str(inv.id),
            'invoice_number': inv.invoice_number,
            'date': str(inv.date),
            'subtotal': str(inv.subtotal),
            'discount': str(inv.discount),
            'tax_amount': str(inv.tax_amount),
            'total': str(inv.total),
            'amount_collected': str(inv.amount_collected),
            'credit_note_amount': str(inv.credit_note_amount or 0),
            'credit_notes': [
                {
                    'id': str(cn.id),
                    'credit_note_number': cn.credit_note_number,
                    'date': str(cn.date),
                    'total': str(cn.total),
                    'reason': cn.reason or '',
                }
                for cn in inv.credit_notes.filter(is_deleted=False).order_by('-date_added')
            ],
            'invoice_type': inv.invoice_type,
            'remarks': inv.remarks or '',
            'show_warranty_in_pdf': inv.show_warranty_in_pdf,
            'customer': {
                'id': str(inv.customer.id) if inv.customer else '',
                'name': inv.customer.name if inv.customer else '',
                'phone': inv.customer.phone if inv.customer else '',
                'whatsapp': inv.customer.whatsapp_number if inv.customer and inv.customer.whatsapp_number else '',
                'email': inv.customer.email if inv.customer and inv.customer.email else '',
                'address': inv.customer.address if inv.customer and inv.customer.address else '',
                'type': inv.customer.customer_type.name if inv.customer and inv.customer.customer_type else 'Regular',
                'tax_number': inv.customer.tax_number if inv.customer and inv.customer.tax_number else '',
                'tin_number': inv.customer.tin_number if inv.customer and inv.customer.tin_number else '',
            },
            'vehicle': {
                'id': str(inv.vehicle.id) if inv.vehicle else '',
                'number': inv.vehicle.vehicle_number if inv.vehicle else '',
                'make': inv.vehicle.make.name if inv.vehicle and inv.vehicle.make else '',
                'model': inv.vehicle.brand_model.name if inv.vehicle and inv.vehicle.brand_model else (inv.vehicle.vehicle_type_model.name if inv.vehicle and inv.vehicle.vehicle_type_model else ''),
                'segment': inv.vehicle.vehicle_type_model.name if inv.vehicle and inv.vehicle.vehicle_type_model else '',
                'type': inv.vehicle.vehicle_type.name if inv.vehicle and inv.vehicle.vehicle_type else (inv.vehicle.vehicle_type_model.vehicle_type.name if inv.vehicle and inv.vehicle.vehicle_type_model and inv.vehicle.vehicle_type_model.vehicle_type else ''),
                'color': inv.vehicle.color.name if inv.vehicle and inv.vehicle.color else '',
                'fuel_type': inv.vehicle.get_fuel_type_display() if inv.vehicle and inv.vehicle.fuel_type else '',
                'wheel_type': inv.vehicle.get_wheel_type_display() if inv.vehicle and inv.vehicle.wheel_type else '',
                'emission_standard': inv.vehicle.emission_standard.name if inv.vehicle and inv.vehicle.emission_standard else '',
            },
            'branch': inv.branch.name if inv.branch else '',
            'branch_address': inv.branch.address if inv.branch and hasattr(inv.branch, 'address') else '',
            'branch_phone': inv.branch.phone if inv.branch and hasattr(inv.branch, 'phone') else '',
            'branch_email': inv.branch.email if inv.branch and hasattr(inv.branch, 'email') else '',
            'branch_gst': inv.branch.gst_number if inv.branch and hasattr(inv.branch, 'gst_number') else '',
            'company_trn': (inv.branch.gst_number if inv.branch and inv.branch.gst_number else (inv.branch.company.gst_number or inv.branch.company.tin_pan_no if inv.branch and inv.branch.company else '')) or '',
            'payment_mode': (
                dict(Receipt.PAYMENT_CHOICES).get(
                    inv.receipts.filter(is_deleted=False).order_by('-date_added').first().payment_mode,
                    inv.receipts.filter(is_deleted=False).order_by('-date_added').first().payment_mode.replace('_', ' ').title()
                ) if inv.receipts.filter(is_deleted=False).exists()
                else ('Credit' if inv.invoice_type == 'creditinvoice' else 'Cash')
            ),
            'branch_logo': request.build_absolute_uri(inv.branch.logo.url) if inv.branch and inv.branch.logo else '',
            'company_logo': request.build_absolute_uri(inv.branch.company.logo_color.url) if inv.branch and inv.branch.company and inv.branch.company.logo_color else '',
            'company_seal': request.build_absolute_uri(inv.branch.company.company_seal.url) if inv.branch and inv.branch.company and getattr(inv.branch.company, 'company_seal', None) else '',
            'services': services_data,
            'extras': extras_data,
            'trading_items': [
                {
                    'id': str(item.stock_item.id),
                    'item_name': item.service_name,
                    'qty': float(item.qty) if item.qty else 1.0,
                    'rate': str(item.rate),
                    'discount': str(item.discount),
                    'is_operational': item.is_operational,
                    'remarks': item.remarks or '',
                }
                for item in inv.items.all() if item.stock_item
            ],
            'assigned_staffs': [
                {'id': str(st.id), 'name': st.name} for st in inv.assigned_staffs.all()
            ],
            'reminders': reminders_data,
            'custom_reminders': custom_reminders_data,
            'customisation': {
                'non_tax_title': inv.branch.invoice_customisation.non_tax_title if inv.branch and hasattr(inv.branch, 'invoice_customisation') and inv.branch.invoice_customisation else 'PROFORMA INVOICE',
                'show_vehicle_number': inv.branch.invoice_customisation.show_vehicle_number if inv.branch and hasattr(inv.branch, 'invoice_customisation') and inv.branch.invoice_customisation else True,
                'show_vehicle_make': inv.branch.invoice_customisation.show_vehicle_make if inv.branch and hasattr(inv.branch, 'invoice_customisation') and inv.branch.invoice_customisation else True,
                'show_vehicle_model': inv.branch.invoice_customisation.show_vehicle_model if inv.branch and hasattr(inv.branch, 'invoice_customisation') and inv.branch.invoice_customisation else True,
                'show_vehicle_segment': inv.branch.invoice_customisation.show_vehicle_segment if inv.branch and hasattr(inv.branch, 'invoice_customisation') and inv.branch.invoice_customisation else True,
                'show_vehicle_type': inv.branch.invoice_customisation.show_vehicle_type if inv.branch and hasattr(inv.branch, 'invoice_customisation') and inv.branch.invoice_customisation else True,
                'show_vehicle_color': inv.branch.invoice_customisation.show_vehicle_color if inv.branch and hasattr(inv.branch, 'invoice_customisation') and inv.branch.invoice_customisation else True,
                'show_vehicle_fuel_type': inv.branch.invoice_customisation.show_vehicle_fuel_type if inv.branch and hasattr(inv.branch, 'invoice_customisation') and inv.branch.invoice_customisation else True,
                'show_vehicle_wheel_type': inv.branch.invoice_customisation.show_vehicle_wheel_type if inv.branch and hasattr(inv.branch, 'invoice_customisation') and inv.branch.invoice_customisation else True,
                'show_vehicle_emission_std': inv.branch.invoice_customisation.show_vehicle_emission_std if inv.branch and hasattr(inv.branch, 'invoice_customisation') and inv.branch.invoice_customisation else True,
                'show_vehicle_odometer': inv.branch.invoice_customisation.show_vehicle_odometer if inv.branch and hasattr(inv.branch, 'invoice_customisation') and inv.branch.invoice_customisation else True,
            },
        })

    return JsonResponse({'success': True, 'invoices': results})

@login_required
def sales_report(request):

    invoices = Invoice.objects.filter(is_deleted=False).order_by('-date')

    # COMPANY FILTER

    user = request.user

    role = None

    if hasattr(user, 'profile') and user.profile.role:
        role = user.profile.role.name

    if role == 'COMPANY_ADMIN':

        if hasattr(user.profile, 'company') and user.profile.company:

            company = user.profile.company

            invoices = invoices.filter(
                branch__company=company
            )

            branches = Branch.objects.filter(
                company=company,
                is_deleted=False
            )

        else:

            branches = Branch.objects.filter(
                is_deleted=False
            )

    elif role == 'BRANCH_ADMIN':
        if hasattr(user, 'managed_branch') and user.managed_branch:
            invoices = invoices.filter(branch=user.managed_branch)
        branches = None
    else:
        branches = Branch.objects.filter(is_deleted=False)
    print("branches",branches)
    
    # Filters
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    invoice_number = request.GET.get('invoice_number')
    payment_mode = request.GET.get('payment_mode', '').strip()

    if from_date:
        invoices = invoices.filter(date__gte=from_date)

    if to_date:
        invoices = invoices.filter(date__lte=to_date)

    if invoice_number:
        invoices = invoices.filter(invoice_number=invoice_number)

    if payment_mode:
        invoices = invoices.filter(receipts__payment_mode=payment_mode).distinct()

    # Balance Calculation
    invoices = invoices.annotate(
        balance=ExpressionWrapper(
            F('total') - F('amount_collected'),
            output_field=DecimalField(max_digits=12, decimal_places=2)
        )
    )

    # Totals
    total_amount = invoices.aggregate(
        total=Sum('total')
    )['total'] or 0

    total_collection = invoices.aggregate(
        collected=Sum('amount_collected')
    )['collected'] or 0

    total_balance = total_amount - total_collection

    context = {
        'invoices': invoices,
        'total_amount': total_amount,
        'total_collection': total_collection,
        'total_balance': total_balance,
        'invoice_number': invoice_number,
        'payment_mode': payment_mode,
        'branches': branches,
    }

    return render(request, 'reports/sales_report.html', context)


@login_required
def invoice_receipt(request, pk):

    invoice = get_object_or_404(
        Invoice.objects.prefetch_related('items', 'credit_notes'),
        pk=pk,
        is_deleted=False
    )

    credit_note_amount = invoice.credit_note_amount or Decimal('0.00')
    balance = max(Decimal('0.00'), invoice.total - invoice.amount_collected - credit_note_amount)

    context = {
        'invoice': invoice,
        'balance': balance,
    }

    return render(request, 'invoice/invoice_receipt.html', context)


def invoice_thermal_receipt(request, pk):
    from decimal import Decimal
    import re
    invoice = get_object_or_404(
        Invoice.objects.select_related(
            'customer', 'vehicle', 'vehicle__vehicle_type_model', 'branch', 'branch__company'
        ).prefetch_related('items', 'credit_notes', 'receipts'),
        pk=pk,
        is_deleted=False
    )
    width = request.GET.get('width', '80')
    if width not in ['58', '80', '100']:
        width = '80'

    credit_note_amount = invoice.credit_note_amount or Decimal('0.00')
    balance = max(Decimal('0.00'), invoice.total - invoice.amount_collected - credit_note_amount)

    company_name = 'AL BAB AL ABYAD AUTO SERVICES L.L.C'
    if invoice.branch and invoice.branch.company and invoice.branch.company.company_name:
        company_name = invoice.branch.company.company_name

    company_trn = ''
    if invoice.branch:
        if invoice.branch.gst_number:
            company_trn = invoice.branch.gst_number
        elif invoice.branch.company:
            company_trn = invoice.branch.company.gst_number or invoice.branch.company.tin_pan_no or ''
    elif invoice.customer and invoice.customer.company:
        company_trn = invoice.customer.company.gst_number or invoice.customer.company.tin_pan_no or ''
    if company_trn:
        company_trn = re.sub(r'^(TRN\s*:\s*|TRN\s*|-|:\s*)', '', str(company_trn).strip(), flags=re.IGNORECASE).strip()

    address_lines = []
    if invoice.branch and invoice.branch.address:
        for line in invoice.branch.address.splitlines():
            line = line.strip()
            if not line:
                continue
            if re.search(r'\bTRN\b|\bGSTIN?\b', line, re.IGNORECASE):
                continue
            if re.search(r'^\+?[0-9\s\-]+$', line):
                continue
            if '@' in line or 'www.' in line:
                continue
            address_lines.append(line)
    if not address_lines:
        address_lines = ['Industrial Area 4', 'Sharjah', 'United Arab Emirates']

    currency = 'AED'
    if invoice.branch and invoice.branch.company and invoice.branch.company.country:
        currency = getattr(invoice.branch.company.country, 'currency_symbol', 'AED') or 'AED'

    logo_url = ''
    if invoice.branch and invoice.branch.company:
        if invoice.branch.company.logo_bw:
            logo_url = invoice.branch.company.logo_bw.url
        elif invoice.branch.company.logo_color:
            logo_url = invoice.branch.company.logo_color.url

    items_list = []
    for item in invoice.items.all():
        name = item.service_name or (item.service.name if item.service else (item.stock_item.item_name if item.stock_item else 'Service'))
        qty = item.qty or 1
        rate = item.rate or Decimal('0.00')
        tot = item.net_taxable_amount or (qty * rate)
        items_list.append({
            'name': name,
            'qty': int(qty) if qty == int(qty) else qty,
            'rate': f"{rate:.2f}",
            'total': f"{tot:.2f}",
        })

    to_parts = []
    if invoice.vehicle:
        v_num = invoice.vehicle.vehicle_number or ''
        v_model = invoice.vehicle.vehicle_type_model.name if invoice.vehicle.vehicle_type_model else ''
        to_parts.append(f"{v_num} {v_model}".strip())
    if invoice.customer and invoice.customer.name:
        c_name = invoice.customer.name.strip()
        if not to_parts or c_name != to_parts[0]:
            to_parts.append(f"({c_name})")
    to_text = ' '.join(to_parts).strip()

    phone_text = ''
    if invoice.customer and invoice.customer.phone:
        phone_text = invoice.customer.phone
    elif invoice.customer and invoice.customer.whatsapp_number:
        phone_text = invoice.customer.whatsapp_number

    context = {
        'invoice': invoice,
        'company_name': company_name,
        'company_trn': company_trn,
        'address_lines': address_lines,
        'currency': currency,
        'logo_url': logo_url,
        'items_list': items_list,
        'to_text': to_text,
        'phone_text': phone_text,
        'balance': balance,
        'paper_width': width,
        'is_2inch': (width == '58'),
        'is_4inch': (width == '100'),
    }
    return render(request, 'invoice/thermal_receipt_print.html', context)


@login_required
def receipt_list(request):

    receipts = Receipt.objects.filter(
        is_deleted=False
    ).select_related(
        'invoice',
        'invoice__customer'
    ).order_by('-created_at')

    user = request.user
    role = user.profile.role.name if hasattr(user, 'profile') and user.profile.role else None

    if role == 'COMPANY_ADMIN' and hasattr(user.profile, 'company') and user.profile.company:
        receipts = receipts.filter(invoice__branch__company=user.profile.company)
    elif role == 'BRANCH_ADMIN' and hasattr(user, 'managed_branch') and user.managed_branch:
        receipts = receipts.filter(invoice__branch=user.managed_branch)

    search = request.GET.get('search')
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')

    payment_mode = request.GET.get('payment_mode', '').strip()

    if search:
        receipts = receipts.filter(
            Q(receipt_number__icontains=search) |
            Q(invoice__invoice_number__icontains=search) |
            Q(invoice__customer__name__icontains=search)
        )

    if from_date:
        receipts = receipts.filter(created_at__date__gte=from_date)

    if to_date:
        receipts = receipts.filter(created_at__date__lte=to_date)

    if payment_mode:
        receipts = receipts.filter(payment_mode=payment_mode)

    context = {
        'receipts': receipts,
        'search': search,
        'payment_mode': payment_mode,
    }

    return render(request, 'receipt/list.html', context)


@login_required
def receipt_create(request, invoice_id=None):

    invoices = Invoice.objects.filter(
        is_deleted=False
    ).order_by('-id')

    selected_invoice = None

    if invoice_id:
        selected_invoice = get_object_or_404(
            Invoice,
            pk=invoice_id,
            is_deleted=False
        )

    if request.method == 'POST':

        invoice = get_object_or_404(
            Invoice,
            pk=request.POST.get('invoice')
        )

        amount = Decimal(request.POST.get('amount') or 0)

        payment_mode = request.POST.get('payment_mode')
        remarks = request.POST.get('remarks')

        cheque_no = request.POST.get('cheque_no')
        cheque_date = request.POST.get('cheque_date')
        bank_name = request.POST.get('bank_name')

        # Generate Receipt Number
        last_receipt = Receipt.objects.order_by('-id').first()

        if last_receipt:
            try:
                last_no = int(last_receipt.receipt_number.split('-')[-1])
            except:
                last_no = last_receipt.id
        else:
            last_no = 0

        receipt_number = f"RCPT-{str(last_no + 1).zfill(5)}"

        # Create Receipt
        receipt = Receipt.objects.create(
            auto_id=get_auto_id(Receipt),
            receipt_number=receipt_number,
            invoice=invoice,
            amount=amount,
            payment_mode=payment_mode,
            remarks=remarks,
            cheque_no=cheque_no,
            cheque_date=cheque_date if cheque_date else None,
            bank_name=bank_name,
        )

        collection_date_str = request.POST.get('collection_date') or request.POST.get('date')
        if collection_date_str:
            try:
                from datetime import datetime
                from django.utils import timezone
                parsed_date = datetime.strptime(str(collection_date_str).strip()[:10], '%Y-%m-%d').date()
                dt = timezone.datetime.combine(parsed_date, timezone.localtime().time())
                dt = timezone.make_aware(dt) if timezone.is_naive(dt) else dt
                Receipt.objects.filter(id=receipt.id).update(created_at=dt, date_added=dt)
            except Exception:
                pass

        # Update Invoice Collection
        invoice.amount_collected += amount
        invoice.save()

        messages.success(
            request,
            "Receipt created successfully."
        )

        return redirect('receipt_list')

    user = request.user
    company = getattr(user.profile, 'company', None) if hasattr(user, 'profile') else None
    if not company and hasattr(user, 'staff_profile') and user.staff_profile and user.staff_profile.branch:
        company = user.staff_profile.branch.company
    country_obj = getattr(company, 'country', None) if company else None
    is_uae = False
    if country_obj:
        iso = (country_obj.phone_iso_code or '').strip().upper()
        curr = (country_obj.currency_code or '').strip().upper()
        cname = (country_obj.name or '').strip().lower()
        if iso == 'AE' or curr == 'AED' or 'emirates' in cname or 'uae' in cname:
            is_uae = True

    context = {
        'invoices': invoices,
        'selected_invoice': selected_invoice,
        'is_uae': is_uae,
        'title': 'Create Receipt',
    }

    return render(request, 'receipt/create.html', context)

@csrf_exempt
def api_outstanding_list(request):
    """Mobile API: list all invoices with outstanding balance (amount_collected < total)."""
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': 'Only GET allowed'}, status=405)

    user = get_user_from_token(request)
    if not user:
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=401)

    invoices = Invoice.objects.filter(
        is_deleted=False,
        customer__is_deleted=False,
    ).select_related(
        'customer', 'vehicle', 'vehicle__vehicle_type_model', 'branch'
    ).filter(amount_collected__lt=F('total')).order_by('customer__name', '-date')

    role = user.profile.role.name if user.profile.role else None
    if role == 'BRANCH_ADMIN' and hasattr(user, 'managed_branch'):
        invoices = invoices.filter(branch=user.managed_branch)
    elif role == 'COMPANY_ADMIN' and user.profile.company:
        invoices = invoices.filter(branch__company=user.profile.company)
        branch_id = request.GET.get('branch_id')
        if branch_id:
            invoices = invoices.filter(branch_id=branch_id)

    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    if from_date:
        invoices = invoices.filter(date__gte=from_date)
    if to_date:
        invoices = invoices.filter(date__lte=to_date)

    results = []
    total_outstanding = Decimal('0.00')
    for inv in invoices:
        outstanding = inv.total - inv.amount_collected
        total_outstanding += outstanding
        results.append({
            'id': str(inv.id),
            'invoice_number': inv.invoice_number,
            'date': str(inv.date),
            'total': str(inv.total),
            'amount_collected': str(inv.amount_collected),
            'outstanding': str(outstanding),
            'customer': {
                'id': str(inv.customer.id),
                'name': inv.customer.name,
                'phone': inv.customer.phone,
            },
            'vehicle': {
                'number': inv.vehicle.vehicle_number,
                'model': inv.vehicle.vehicle_type_model.name if inv.vehicle.vehicle_type_model else '',
            },
            'branch': inv.branch.name if inv.branch else '',
        })

    return JsonResponse({
        'success': True,
        'invoices': results,
        'total_outstanding': str(total_outstanding),
        'count': len(results),
    })


@csrf_exempt
def api_collect_payment(request):
    """Mobile API: collect partial or full payment for an outstanding invoice."""
    import json
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Only POST allowed'}, status=405)

    user = get_user_from_token(request)
    if not user:
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=401)

    try:
        data = json.loads(request.body)
        invoice_id = data.get('invoice_id')
        amount = Decimal(str(data.get('amount', 0)))

        invoice = Invoice.objects.get(id=invoice_id, is_deleted=False)

        # Scope check
        role = user.profile.role.name if user.profile.role else None
        if role == 'BRANCH_ADMIN' and hasattr(user, 'managed_branch'):
            if invoice.branch != user.managed_branch:
                return JsonResponse({'success': False, 'message': 'Access denied'}, status=403)
        elif role == 'COMPANY_ADMIN' and user.profile.company:
            if invoice.branch.company != user.profile.company:
                return JsonResponse({'success': False, 'message': 'Access denied'}, status=403)

        outstanding = invoice.total - invoice.amount_collected
        if amount <= 0:
            return JsonResponse({'success': False, 'message': 'Amount must be greater than 0'}, status=400)
        if amount > outstanding:
            currency = invoice.branch.company.country.currency_symbol if invoice.branch.company.country else '₹'
            return JsonResponse({'success': False, 'message': f'Amount exceeds outstanding balance of {currency}{outstanding}'}, status=400)

        invoice.amount_collected += amount
        invoice.save()

        receipt_auto_id = get_auto_id(Receipt)
        receipt = Receipt.objects.create(
            auto_id=receipt_auto_id,
            creator=user,
            receipt_number=f"RCPT-{str(receipt_auto_id).zfill(5)}",
            invoice=invoice,
            amount=amount,
            payment_mode=data.get('payment_mode') or 'cash',
            remarks=data.get('remarks') or 'Outstanding collection',
        )

        collection_date_str = data.get('collection_date') or data.get('date')
        if collection_date_str:
            try:
                from datetime import datetime
                from django.utils import timezone
                parsed_date = datetime.strptime(str(collection_date_str).strip()[:10], '%Y-%m-%d').date()
                dt = timezone.datetime.combine(parsed_date, timezone.localtime().time())
                dt = timezone.make_aware(dt) if timezone.is_naive(dt) else dt
                Receipt.objects.filter(id=receipt.id).update(created_at=dt, date_added=dt)
            except Exception:
                pass

        remaining = invoice.total - invoice.amount_collected
        return JsonResponse({
            'success': True,
            'message': 'Payment collected successfully',
            'new_collected': str(invoice.amount_collected),
            'remaining_outstanding': str(remaining),
            'fully_settled': remaining == 0,
            'receipt': {
                'id': str(receipt.id),
                'receipt_number': receipt.receipt_number,
                'amount': str(receipt.amount),
            },
        })

    except Invoice.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Invoice not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


def api_receipt_list(request):
    """Mobile API: list receipts created from outstanding collections."""
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': 'Only GET allowed'}, status=405)

    user = get_user_from_token(request)
    if not user:
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=401)

    receipts = Receipt.objects.filter(is_deleted=False).select_related(
        'invoice',
        'invoice__customer',
        'invoice__vehicle',
        'invoice__vehicle__vehicle_type_model',
        'invoice__branch',
    ).order_by('-created_at', '-auto_id')

    role = user.profile.role.name if user.profile.role else None
    if role == 'BRANCH_ADMIN' and hasattr(user, 'managed_branch'):
        receipts = receipts.filter(invoice__branch=user.managed_branch)
    elif role == 'COMPANY_ADMIN' and user.profile.company:
        receipts = receipts.filter(invoice__branch__company=user.profile.company)
        branch_id = request.GET.get('branch_id')
        if branch_id:
            receipts = receipts.filter(invoice__branch_id=branch_id)

    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    payment_mode = request.GET.get('payment_mode')
    if from_date:
        receipts = receipts.filter(created_at__date__gte=from_date)
    if to_date:
        receipts = receipts.filter(created_at__date__lte=to_date)
    if payment_mode:
        receipts = receipts.filter(payment_mode=payment_mode)

    results = []
    total_collected = Decimal('0.00')
    for receipt in receipts:
        invoice = receipt.invoice
        balance = invoice.total - invoice.amount_collected
        total_collected += receipt.amount
        results.append({
            'id': str(receipt.id),
            'receipt_number': receipt.receipt_number,
            'date': receipt.created_at.date().isoformat(),
            'time': receipt.created_at.strftime('%I:%M %p'),
            'amount': str(receipt.amount),
            'payment_mode': receipt.payment_mode,
            'remarks': receipt.remarks or '',
            'invoice': {
                'id': str(invoice.id),
                'invoice_number': invoice.invoice_number,
                'date': str(invoice.date),
                'total': str(invoice.total),
                'amount_collected': str(invoice.amount_collected),
                'balance': str(balance),
            },
            'customer': {
                'name': invoice.customer.name,
                'phone': invoice.customer.phone,
            },
            'vehicle': {
                'number': invoice.vehicle.vehicle_number if invoice.vehicle else 'Counter Sale',
                'model': invoice.vehicle.vehicle_type_model.name if invoice.vehicle and invoice.vehicle.vehicle_type_model else '',
            },
            'branch': invoice.branch.name if invoice.branch else '',
        })

    return JsonResponse({
        'success': True,
        'receipts': results,
        'total_collected': str(total_collected),
        'count': len(results),
    })


@csrf_exempt
def api_delete_invoice(request):
    """
    Mobile + Web API: Soft-delete an invoice.
    - Marks invoice as is_deleted=True
    - Soft-deletes all associated Receipts
    - Resets invoice.amount_collected to 0
    """
    import json
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Only POST allowed'}, status=405)

    user = get_user_from_token(request)
    if not user:
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=401)

    try:
        data = json.loads(request.body)
        invoice_id = data.get('invoice_id') or data.get('id')
        if not invoice_id:
            return JsonResponse({'success': False, 'message': 'invoice_id is required'}, status=400)

        invoice = Invoice.objects.get(id=invoice_id, is_deleted=False)

        # Scope check
        role = user.profile.role.name if user.profile.role else None
        if role == 'BRANCH_ADMIN' and hasattr(user, 'managed_branch'):
            if invoice.branch != user.managed_branch:
                return JsonResponse({'success': False, 'message': 'Access denied'}, status=403)
        elif role == 'COMPANY_ADMIN' and user.profile.company:
            if invoice.branch.company != user.profile.company:
                return JsonResponse({'success': False, 'message': 'Access denied'}, status=403)

        # Soft-delete all receipts linked to this invoice
        Receipt.objects.filter(invoice=invoice, is_deleted=False).update(is_deleted=True)

        # Reset collected amount and soft-delete invoice
        invoice.amount_collected = Decimal('0.00')
        invoice.is_deleted = True
        invoice.updater = user
        invoice.save()

        return JsonResponse({'success': True, 'message': 'Invoice deleted successfully'})

    except Invoice.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Invoice not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@csrf_exempt
def api_delete_receipt(request):
    """
    Mobile + Web API: Soft-delete a receipt and restore outstanding balance.
    - Marks receipt as is_deleted=True
    - Decrements invoice.amount_collected by the receipt amount
    """
    import json
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Only POST allowed'}, status=405)

    user = get_user_from_token(request)
    if not user:
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=401)

    try:
        data = json.loads(request.body)
        receipt_id = data.get('receipt_id') or data.get('id')
        if not receipt_id:
            return JsonResponse({'success': False, 'message': 'receipt_id is required'}, status=400)

        receipt = Receipt.objects.select_related('invoice').get(id=receipt_id, is_deleted=False)
        invoice = receipt.invoice

        # Scope check
        role = user.profile.role.name if user.profile.role else None
        if role == 'BRANCH_ADMIN' and hasattr(user, 'managed_branch'):
            if invoice.branch != user.managed_branch:
                return JsonResponse({'success': False, 'message': 'Access denied'}, status=403)
        elif role == 'COMPANY_ADMIN' and user.profile.company:
            if invoice.branch.company != user.profile.company:
                return JsonResponse({'success': False, 'message': 'Access denied'}, status=403)

        receipt_amount = receipt.amount

        # Soft-delete receipt
        receipt.is_deleted = True
        receipt.save()

        # Restore the outstanding balance by decrementing amount_collected
        invoice.amount_collected = max(Decimal('0.00'), invoice.amount_collected - receipt_amount)
        invoice.save()

        new_outstanding = invoice.total - invoice.amount_collected
        return JsonResponse({
            'success': True,
            'message': 'Receipt deleted. Amount restored to outstanding.',
            'new_outstanding': str(new_outstanding),
            'new_amount_collected': str(invoice.amount_collected),
        })

    except Receipt.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Receipt not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@csrf_exempt
def api_customer_outstanding_list(request):
    """Mobile API: list all customers who have outstanding invoices."""

    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': 'Only GET allowed'}, status=405)

    user = get_user_from_token(request)
    if not user:
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=401)

    invoices = Invoice.objects.filter(
        is_deleted=False,
        customer__is_deleted=False,
    ).select_related(
        'customer', 'branch'
    ).filter(amount_collected__lt=F('total')).order_by('date', 'auto_id')

    role = user.profile.role.name if user.profile.role else None
    if role == 'BRANCH_ADMIN' and hasattr(user, 'managed_branch'):
        invoices = invoices.filter(branch=user.managed_branch)
    elif role == 'COMPANY_ADMIN' and user.profile.company:
        invoices = invoices.filter(branch__company=user.profile.company)
        branch_id = request.GET.get('branch_id')
        if branch_id:
            invoices = invoices.filter(branch_id=branch_id)

    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    if from_date:
        invoices = invoices.filter(date__gte=from_date)
    if to_date:
        invoices = invoices.filter(date__lte=to_date)

    from collections import defaultdict
    customer_data = defaultdict(lambda: {
        'customer_id': '',
        'customer_name': '',
        'customer_phone': '',
        'total_outstanding': Decimal('0.00'),
        'invoices_count': 0
    })

    for inv in invoices:
        cid = str(inv.customer.id)
        outstanding = inv.total - inv.amount_collected
        customer_data[cid]['customer_id'] = cid
        customer_data[cid]['customer_name'] = inv.customer.name
        customer_data[cid]['customer_phone'] = inv.customer.phone
        customer_data[cid]['total_outstanding'] += outstanding
        customer_data[cid]['invoices_count'] += 1

    results = []
    total_outstanding_sum = Decimal('0.00')
    for item in customer_data.values():
        total_outstanding_sum += item['total_outstanding']
        results.append({
            'customer_id': item['customer_id'],
            'customer_name': item['customer_name'],
            'customer_phone': item['customer_phone'],
            'total_outstanding': str(item['total_outstanding']),
            'invoices_count': item['invoices_count'],
        })

    # Sort by customer name
    results.sort(key=lambda x: x['customer_name'].lower())

    return JsonResponse({
        'success': True,
        'customers': results,
        'total_outstanding': str(total_outstanding_sum),
        'count': len(results),
    })


@csrf_exempt
def api_collect_customer_outstanding(request):
    """Mobile API: collect bulk payment and apply it sequentially to a customer's oldest outstanding invoices."""
    import json
    from django.db import transaction
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Only POST allowed'}, status=405)

    user = get_user_from_token(request)
    if not user:
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=401)

    try:
        data = json.loads(request.body)
        customer_id = data.get('customer_id')
        amount = Decimal(str(data.get('amount', 0)))
        payment_mode = data.get('payment_mode') or 'cash'
        remarks = data.get('remarks') or 'Bulk outstanding collection'
        collection_date_str = data.get('collection_date') or data.get('date')

        if not customer_id:
            return JsonResponse({'success': False, 'message': 'customer_id is required'}, status=400)
        if amount <= 0:
            return JsonResponse({'success': False, 'message': 'Amount must be greater than 0'}, status=400)

        with transaction.atomic():
            invoices = Invoice.objects.select_for_update().filter(
                customer_id=customer_id,
                is_deleted=False,
                amount_collected__lt=F('total')
            ).order_by('date', 'auto_id')

            role = user.profile.role.name if user.profile.role else None
            if role == 'BRANCH_ADMIN' and hasattr(user, 'managed_branch'):
                invoices = invoices.filter(branch=user.managed_branch)
            elif role == 'COMPANY_ADMIN' and user.profile.company:
                invoices = invoices.filter(branch__company=user.profile.company)

            total_outstanding = sum(inv.total - inv.amount_collected for inv in invoices)
            if amount > total_outstanding:
                return JsonResponse({
                    'success': False,
                    'message': f'Collection amount exceeds total outstanding balance ({total_outstanding})'
                }, status=400)

            amount_left = amount
            receipts_created = []

            for inv in invoices:
                if amount_left <= 0:
                    break

                inv_outstanding = inv.total - inv.amount_collected
                payment_to_apply = min(amount_left, inv_outstanding)

                inv.amount_collected += payment_to_apply
                inv.save()

                receipt_auto_id = get_auto_id(Receipt)
                rcpt = Receipt.objects.create(
                    auto_id=receipt_auto_id,
                    creator=user,
                    receipt_number=f"RCPT-{str(receipt_auto_id).zfill(5)}",
                    invoice=inv,
                    amount=payment_to_apply,
                    payment_mode=payment_mode,
                    remarks=remarks,
                )

                if collection_date_str:
                    try:
                        from datetime import datetime
                        from django.utils import timezone
                        parsed_date = datetime.strptime(str(collection_date_str).strip()[:10], '%Y-%m-%d').date()
                        dt = timezone.datetime.combine(parsed_date, timezone.localtime().time())
                        dt = timezone.make_aware(dt) if timezone.is_naive(dt) else dt
                        Receipt.objects.filter(id=rcpt.id).update(created_at=dt, date_added=dt)
                    except Exception:
                        pass

                receipts_created.append({
                    'id': str(rcpt.id),
                    'receipt_number': rcpt.receipt_number,
                    'invoice_number': inv.invoice_number,
                    'amount_applied': str(payment_to_apply),
                })

                amount_left -= payment_to_apply

            return JsonResponse({
                'success': True,
                'message': 'Bulk payment applied sequentially successfully',
                'amount_collected': str(amount),
                'receipts': receipts_created,
            })

    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@login_required
def job_report(request):

    from django.db.models import Sum, Count, Q, ExpressionWrapper, F, DecimalField
    from finance_management.models import Invoice
    from service_management.models import ServiceType, BranchServiceCategory, Service, BranchService, CompanyService
    from client_management.models import Client

    today = timezone.localdate() if hasattr(timezone, 'localdate') else timezone.now().date()
    today_str = today.strftime('%Y-%m-%d')

    from_date_param = request.GET.get('from_date') if 'from_date' in request.GET else request.GET.get('fromdate')
    to_date_param = request.GET.get('to_date') if 'to_date' in request.GET else request.GET.get('todate')

    if from_date_param is None:
        from_date = today_str
    else:
        from_date = from_date_param.strip()

    if to_date_param is None:
        to_date = today_str
    else:
        to_date = to_date_param.strip()

    company_param = request.GET.get('company')
    branch_id = request.GET.get('branch')
    category_param = request.GET.get('category')
    search = request.GET.get('search')

    invoices = Invoice.objects.filter(
        is_deleted=False
    ).select_related(
        'customer',
        'vehicle',
        'branch',
        'branch__company',
        'branch__company__country'
    ).prefetch_related(
        'items'
    )

    # COMPANY & ROLE FILTER
    user = request.user
    role = None
    if hasattr(user, 'profile') and user.profile.role:
        role = user.profile.role.name

    companies = None
    selected_company = None

    if role == 'COMPANY_ADMIN':
        if hasattr(user.profile, 'company') and user.profile.company:
            selected_company = user.profile.company
            invoices = invoices.filter(
                branch__company=selected_company
            )
            branches = Branch.objects.filter(
                company=selected_company,
                is_deleted=False
            )
        else:
            branches = Branch.objects.filter(
                is_deleted=False
            )
    elif role == 'BRANCH_ADMIN':
        if hasattr(user, 'managed_branch') and user.managed_branch:
            invoices = invoices.filter(branch=user.managed_branch)
            selected_company = user.managed_branch.company
        branches = None
    else:
        companies = Client.objects.filter(is_deleted=False).order_by('company_name')
        if company_param:
            selected_company = Client.objects.filter(id=company_param, is_deleted=False).first()
            if selected_company:
                invoices = invoices.filter(branch__company=selected_company)
                branches = Branch.objects.filter(company=selected_company, is_deleted=False)
            else:
                branches = Branch.objects.filter(is_deleted=False)
        else:
            branches = Branch.objects.filter(is_deleted=False)

    # BRANCH FILTER
    if branch_id:
        invoices = invoices.filter(
            branch_id=branch_id
        )
        if not selected_company:
            branch_obj = Branch.objects.filter(id=branch_id).select_related('company').first()
            if branch_obj and branch_obj.company:
                selected_company = branch_obj.company

    # Fetch Enabled Categories for Category Filter
    all_types = ServiceType.objects.filter(is_deleted=False).order_by('name')

    target_branch_id = branch_id
    if not target_branch_id and role == 'BRANCH_ADMIN' and hasattr(user, 'managed_branch') and user.managed_branch:
        target_branch_id = user.managed_branch.id

    if target_branch_id:
        bsc_qs = BranchServiceCategory.objects.filter(branch_id=target_branch_id, is_deleted=False, is_enabled=True)
        enabled_type_ids = set(bsc_qs.values_list('service_type_id', flat=True))
        enabled_type_ids.update(
            BranchService.objects.filter(branch_id=target_branch_id, is_enabled=True, is_deleted=False).values_list('service__service_type_id', flat=True)
        )
        enabled_slugs = set(bsc_qs.values_list('service_type__slug', flat=True))
        categories = [
            st for st in all_types
            if st.id in enabled_type_ids or (st.slug and st.slug in enabled_slugs)
        ]
    elif selected_company:
        bsc_qs = BranchServiceCategory.objects.filter(branch__company=selected_company, is_deleted=False, is_enabled=True)
        enabled_type_ids = set(bsc_qs.values_list('service_type_id', flat=True))
        enabled_slugs = set(bsc_qs.values_list('service_type__slug', flat=True))
        enabled_type_ids.update(
            CompanyService.objects.filter(company=selected_company, is_enabled=True, is_deleted=False).values_list('service__service_type_id', flat=True)
        )
        categories = [
            st for st in all_types
            if st.id in enabled_type_ids or (st.slug and st.slug in enabled_slugs)
        ]
    else:
        categories = list(all_types)

    # SEARCH
    if search:
        invoices = invoices.filter(
            Q(invoice_number__icontains=search) |
            Q(customer__name__icontains=search) |
            Q(customer__phone__icontains=search) |
            Q(vehicle__vehicle_number__icontains=search)
        )

    # DATE FILTER
    if from_date:
        invoices = invoices.filter(
            date__gte=from_date
        )

    if to_date:
        invoices = invoices.filter(
            date__lte=to_date
        )

    # CATEGORY FILTER
    if category_param:
        is_uuid = False
        target_st = None
        try:
            import uuid
            uuid_val = uuid.UUID(str(category_param))
            is_uuid = True
            target_st = ServiceType.objects.filter(id=uuid_val).first()
        except (ValueError, AttributeError, TypeError):
            is_uuid = False

        if not target_st:
            target_st = ServiceType.objects.filter(slug=category_param, is_deleted=False).first()
        if not target_st:
            target_st = ServiceType.objects.filter(name__iexact=category_param, is_deleted=False).first()

        if target_st:
            aliases = [target_st.slug] if target_st.slug else []
            s_slug = target_st.slug or ''
            s_name = target_st.name.lower()
            if 'detail' in s_slug or 'detail' in s_name:
                aliases.extend(['detailing', 'car_detailing'])
            if 'align' in s_slug or 'align' in s_name:
                aliases.extend(['wheel_alignment', 'wheel_balancing'])
            if 'insur' in s_slug or 'insur' in s_name:
                aliases.extend(['auto_insurance', 'insurance'])
            if 'antirust' in s_slug or 'antirust' in s_name:
                aliases.extend(['under_body_antirust_coating', 'under_body_antirust_coating_1'])
            if 'oil' in s_slug or 'oil' in s_name:
                aliases.extend(['oil_change'])
            if 'tyre' in s_slug or 'tyre' in s_name:
                aliases.extend(['tyre_change', 'tyre_services'])
            if 'wash' in s_slug or 'wash' in s_name:
                aliases.extend(['washing', 'car_wash'])
            if 'smoke' in s_slug or 'smoke' in s_name:
                aliases.extend(['smoke_test', 'smoke_test_1'])
            aliases = list(set(aliases))

            svc_names = list(Service.objects.filter(service_type=target_st).values_list('name', flat=True))

            cat_q = (
                Q(items__service__service_type=target_st) |
                Q(items__service__service_type__slug=target_st.slug) |
                Q(items__service_detail__service_category__in=aliases)
            )
            if svc_names:
                cat_q |= Q(items__service_name__in=svc_names)
            cat_q |= Q(items__service_name__iexact=target_st.name)

            invoices = invoices.filter(cat_q).distinct()
        else:
            if is_uuid:
                cat_q = Q(items__service__service_type__id=category_param) | Q(items__service__service_type__slug=category_param)
            else:
                cat_q = Q(items__service__service_type__slug=category_param) | Q(items__service_detail__service_category=category_param)
            invoices = invoices.filter(cat_q).distinct()

    invoices = invoices.order_by(
        '-date',
        '-auto_id'
    )
    for invoice in invoices:
        invoice.balance = invoice.total - invoice.amount_collected

    # Resolve currency symbol
    currency_symbol = '₹'
    if selected_company and getattr(selected_company, 'country', None) and selected_company.country.currency_symbol:
        currency_symbol = selected_company.country.currency_symbol
    elif hasattr(user, 'profile') and getattr(user.profile, 'company', None) and getattr(user.profile.company, 'country', None) and user.profile.company.country.currency_symbol:
        currency_symbol = user.profile.company.country.currency_symbol
    elif hasattr(user, 'managed_branch') and user.managed_branch and getattr(user.managed_branch.company, 'country', None) and user.managed_branch.company.country.currency_symbol:
        currency_symbol = user.managed_branch.company.country.currency_symbol

    # SUMMARY
    summary = invoices.aggregate(
        total_jobs=Count('id'),
        total_revenue=Sum('total'),
        total_collected=Sum('amount_collected'),
        total_balance=Sum(
            ExpressionWrapper(
                F('total') - F('amount_collected'),
                output_field=DecimalField()
            )
        ),
        total_discount=Sum('discount'),
    )

    context = {
        'invoices': invoices,
        'companies': companies,
        'selected_company_id': str(selected_company.id) if selected_company else (company_param or ''),
        'branches': branches,
        'categories': categories,
        'from_date': from_date,
        'to_date': to_date,
        'branch_id': branch_id,
        'category': category_param,
        'search': search,
        'currency_symbol': currency_symbol,
        'total_jobs': summary['total_jobs'] or 0,
        'total_revenue': summary['total_revenue'] or 0,
        'total_collected': summary['total_collected'] or 0,
        'total_balance': summary['total_balance'] or 0,
        'total_discount': summary['total_discount'] or 0,
    }

    return render(
        request,
        'reports/job_report.html',
        context
    )


@login_required
def booking_report(request):

    bookings = Booking.objects.select_related('customer','vehicle','branch').filter(is_deleted=False)

    role = request.user.profile.role.name if request.user.profile.role else None

    if role == 'BRANCH_ADMIN' and hasattr(request.user, 'managed_branch'):

        bookings = bookings.filter(
            branch=request.user.managed_branch
        )

    elif role == 'COMPANY_ADMIN' and request.user.profile.company:

        bookings = bookings.filter(
            branch__company=request.user.profile.company
        )

    search = request.GET.get('search', '')
    status = request.GET.get('status', '')
    from_date = request.GET.get('from_date', '')
    to_date = request.GET.get('to_date', '')

    if search:

        bookings = bookings.filter(
            Q(customer__name__icontains=search) |
            Q(customer__phone__icontains=search) |
            Q(vehicle__vehicle_number__icontains=search)
        )

    # STATUS

    if status:

        bookings = bookings.filter(
            status=status
        )

    if from_date:

        bookings = bookings.filter(
            booking_date__gte=from_date
        )

    if to_date:

        bookings = bookings.filter(
            booking_date__lte=to_date
        )

    bookings = bookings.order_by('-booking_date','-id')

    paginator = Paginator(bookings, 20)

    page_number = request.GET.get('page')

    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'search': search,
        'status': status,
        'from_date': from_date,
        'to_date': to_date,
        'status_choices': Booking.STATUS_CHOICES,
    }

    return render(request, 'reports/booking_report.html', context)


@login_required
def cancellation_report(request):

    cancellations = Booking.objects.select_related(
        'customer',
        'vehicle',
        'branch'
    ).filter(
        is_deleted=False,
        status='cancelled'
    )

    role = request.user.profile.role.name if request.user.profile.role else None

    if role == 'BRANCH_ADMIN' and hasattr(request.user, 'managed_branch'):

        cancellations = cancellations.filter(
            branch=request.user.managed_branch
        )

    elif role == 'COMPANY_ADMIN' and request.user.profile.company:

        cancellations = cancellations.filter(
            branch__company=request.user.profile.company
        )

    search = request.GET.get('search', '')
    from_date = request.GET.get('from_date', '')
    to_date = request.GET.get('to_date', '')

    if search:

        cancellations = cancellations.filter(
            Q(customer__name__icontains=search) |
            Q(customer__mobile__icontains=search) |
            Q(vehicle__vehicle_number__icontains=search)
        )

    if from_date:

        cancellations = cancellations.filter(
            booking_date__gte=from_date
        )

    if to_date:

        cancellations = cancellations.filter(
            booking_date__lte=to_date
        )

    cancellations = cancellations.order_by(
        '-booking_date',
        '-id'
    )

    paginator = Paginator(cancellations, 20)

    page_number = request.GET.get('page')

    page_obj = paginator.get_page(page_number)

    total_cancelled = cancellations.count()

    context = {
        'page_obj': page_obj,
        'search': search,
        'from_date': from_date,
        'to_date': to_date,
        'total_cancelled': total_cancelled,
    }

    return render(request,'reports/cancellation_report.html',context)



@login_required
def profit_report(request):

    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    branch_id = request.GET.get('branch')

    income_rows = []
    expense_rows = []

    total_income = 0
    total_expense = 0
    net_profit = 0
    total_outstanding = 0

    role = request.user.profile.role.name if request.user.profile.role else None

    branches = Branch.objects.filter(is_deleted=False)

    if role == 'BRANCH_ADMIN' and hasattr(request.user, 'managed_branch'):

        branches = branches.filter(
            id=request.user.managed_branch.id
        )

    elif role == 'COMPANY_ADMIN' and request.user.profile.company:

        branches = branches.filter(
            company=request.user.profile.company
        )

    if from_date and to_date:

        invoice_filter = {
            'invoice__is_deleted': False,
            'invoice__date__gte': from_date,
            'invoice__date__lte': to_date,
        }

        invoice_direct_filter = {
            'is_deleted': False,
            'date__gte': from_date,
            'date__lte': to_date,
        }

        expense_filter = {
            'is_deleted': False,
            'expense_date__gte': from_date,
            'expense_date__lte': to_date,
        }

        if role == 'BRANCH_ADMIN' and hasattr(request.user, 'managed_branch'):

            invoice_filter['invoice__branch'] = (
                request.user.managed_branch
            )
            invoice_direct_filter['branch'] = (
                request.user.managed_branch
            )

            expense_filter['branch'] = (
                request.user.managed_branch
            )

        elif role == 'COMPANY_ADMIN' and request.user.profile.company:

            invoice_filter['invoice__branch__company'] = (
                request.user.profile.company
            )
            invoice_direct_filter['branch__company'] = (
                request.user.profile.company
            )

            expense_filter['branch__company'] = (
                request.user.profile.company
            )

        if branch_id:

            if branches.filter(id=branch_id).exists():

                invoice_filter['invoice__branch_id'] = branch_id
                invoice_direct_filter['branch_id'] = branch_id
                expense_filter['branch_id'] = branch_id

        income_rows = (
            InvoiceItem.objects
            .filter(**invoice_filter)
            .values('service_name')
            .annotate(
                amount=Sum(
                    F('rate') - F('discount')
                )
            )
            .order_by('-amount')
        )

        total_income = sum(
            float(item['amount'] or 0)
            for item in income_rows
        )
        
        expense_rows = (
            ExpenseEntry.objects
            .filter(**expense_filter)
            .values(
                'expense__expense_head__name'
            )
            .annotate(
                amount=Sum('amount')
            )
            .order_by('-amount')
        )

        total_expense = sum(
            float(item['amount'] or 0)
            for item in expense_rows
        )

        net_profit = total_income - total_expense
        invoices = Invoice.objects.filter(**invoice_direct_filter)
        total_outstanding = sum(float((inv.total or 0) - (inv.amount_collected or 0)) for inv in invoices)

    context = {
        'branches': branches,
        'branch_id': branch_id,
        'from_date': from_date,
        'to_date': to_date,
        'income_rows': income_rows,
        'expense_rows': expense_rows,
        'total_income': total_income,
        'total_expense': total_expense,
        'net_profit': net_profit,
        'total_outstanding': total_outstanding,
    }

    return render(
        request,
        'reports/profit_report.html',
        context
    )
    

@login_required
def profit_report_pdf(request):

    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    branch_id = request.GET.get('branch')

    income_rows = []
    expense_rows = []

    total_income = 0
    total_expense = 0
    net_profit = 0

    role = request.user.profile.role.name if request.user.profile.role else None

    branches = Branch.objects.filter(is_deleted=False)
    print("companny",request.user.profile.company)

    if role == 'BRANCH_ADMIN' and hasattr(request.user, 'managed_branch'):
        branches = branches.filter(
            id=request.user.managed_branch.id
        )

    elif role == 'COMPANY_ADMIN' and request.user.profile.company:
        branches = branches.filter(
            company=request.user.profile.company
        )

    invoice_filter = {
        'invoice__is_deleted': False,
    }

    invoice_direct_filter = {
        'is_deleted': False,
    }

    expense_filter = {
        'is_deleted': False,
    }

    if from_date:
        invoice_filter['invoice__date__gte'] = from_date
        invoice_direct_filter['date__gte'] = from_date
        expense_filter['expense_date__gte'] = from_date

    if to_date:
        invoice_filter['invoice__date__lte'] = to_date
        invoice_direct_filter['date__lte'] = to_date
        expense_filter['expense_date__lte'] = to_date

    if role == 'BRANCH_ADMIN' and hasattr(request.user, 'managed_branch'):

        invoice_filter['invoice__branch'] = request.user.managed_branch
        invoice_direct_filter['branch'] = request.user.managed_branch
        expense_filter['branch'] = request.user.managed_branch

    elif role == 'COMPANY_ADMIN' and request.user.profile.company:

        invoice_filter['invoice__branch__company'] = request.user.profile.company
        invoice_direct_filter['branch__company'] = request.user.profile.company
        expense_filter['branch__company'] = request.user.profile.company

    if branch_id and branches.filter(id=branch_id).exists():

        invoice_filter['invoice__branch_id'] = branch_id
        invoice_direct_filter['branch_id'] = branch_id
        expense_filter['branch_id'] = branch_id

    income_rows = (
        InvoiceItem.objects
        .filter(**invoice_filter)
        .values('service_name')
        .annotate(
            amount=Sum(F('rate') - F('discount'))
        )
        .order_by('-amount')
    )

    total_income = sum(
        float(item['amount'] or 0)
        for item in income_rows
    )

    expense_rows = (
        ExpenseEntry.objects
        .filter(**expense_filter)
        .values(
            'expense__expense_head__name'
        )
        .annotate(
            amount=Sum('amount')
        )
        .order_by('-amount')
    )

    total_expense = sum(
        float(item['amount'] or 0)
        for item in expense_rows
    )

    net_profit = total_income - total_expense
    invoices = Invoice.objects.filter(**invoice_direct_filter)
    total_outstanding = sum(float((inv.total or 0) - (inv.amount_collected or 0)) for inv in invoices)

    context = {
        'from_date': from_date,
        'to_date': to_date,
        'income_rows': income_rows,
        'expense_rows': expense_rows,
        'total_income': total_income,
        'total_expense': total_expense,
        'net_profit': net_profit,
        'total_outstanding': total_outstanding,
        "company": request.user.profile.company,
    }

    html_string = render_to_string(
        'reports/profit_report_pdf.html',
        context
    )

    html = HTML(
        string=html_string,
        base_url=request.build_absolute_uri('/')
    )

    pdf = html.write_pdf()

    response = HttpResponse(
        pdf,
        content_type='application/pdf'
    )

    response['Content-Disposition'] = (
        'inline; filename="profit_report.pdf"'
    )

    return response

@login_required
def expense_report(request):

    role = getattr(
        getattr(request.user, 'profile', None),
        'role',
        None
    )

    role_name = role.name if role else None

    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    branch_id = request.GET.get('branch')
    expense_head_id = request.GET.get('expense_head')


    today = timezone.now().date()

    if not from_date:
        from_date = today

    if not to_date:
        to_date = today


    if role_name == 'COMPANY_ADMIN':

        company = getattr(
            request.user.profile,
            'company',
            None
        )

        branches = Branch.objects.filter(
            company=company,
            is_deleted=False
        )

        expenses = ExpenseEntry.objects.filter(
            company=company,
            expense_date__gte=from_date,
            expense_date__lte=to_date,
            is_deleted=False
        ).select_related(
            'branch',
            'expense',
            'expense__expense_head'
        )

        if branch_id:

            expenses = expenses.filter(
                branch_id=branch_id
            )


    else:

        branch = getattr(
            request.user,
            'managed_branch',
            None
        )

        branches = None

        expenses = ExpenseEntry.objects.filter(
            branch=branch,
            expense_date__gte=from_date,
            expense_date__lte=to_date,
            is_deleted=False
        ).select_related(
            'branch',
            'expense',
            'expense__expense_head'
        )


    if expense_head_id:

        expenses = expenses.filter(
            expense__expense_head_id=expense_head_id
        )

    total_expense = expenses.aggregate(
        total=Sum('amount')
    )['total'] or 0

    expense_heads = ExpenseHead.objects.filter(
        company=company,
        is_deleted=False
    )

    context = {

        'expenses': expenses,
        'branches': branches,
        'expense_heads': expense_heads,

        'from_date': from_date,
        'to_date': to_date,
        'branch_id': branch_id,
        'expense_head_id': expense_head_id,

        'total_expense': total_expense,

        'title': 'Expense Report'
    }

    return render(request,'reports/expense_report.html',context)


@login_required
def expense_head_report(request):

    role = getattr(
        getattr(request.user, 'profile', None),
        'role',
        None
    )

    role_name = role.name if role else None

    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    branch_id = request.GET.get('branch')

    today = timezone.now().date()

    if not from_date:
        from_date = today

    if not to_date:
        to_date = today

    if role_name == 'COMPANY_ADMIN':

        company = request.user.profile.company

        branches = Branch.objects.filter(
            company=company,
            is_deleted=False
        )

        expenses = ExpenseEntry.objects.filter(
            company=company,
            expense_date__gte=from_date,
            expense_date__lte=to_date,
            is_deleted=False
        )

        if branch_id:

            expenses = expenses.filter(
                branch_id=branch_id
            )

    else:

        branch = request.user.managed_branch

        branches = None

        expenses = ExpenseEntry.objects.filter(
            branch=branch,
            expense_date__gte=from_date,
            expense_date__lte=to_date,
            is_deleted=False
        )
        
    expense_head_data = expenses.values(
        'expense__expense_head__id',
        'expense__expense_head__name'
    ).annotate(
        total_amount=Coalesce(
        Sum('amount'),
        Value(0),
        output_field=DecimalField()
    )
    ).order_by(
        '-total_amount'
    )

    total_expense = expenses.aggregate(
        total=Sum('amount')
    )['total'] or 0

    context = {

        'expense_head_data': expense_head_data,
        'branches': branches,

        'from_date': from_date,
        'to_date': to_date,
        'branch_id': branch_id,

        'total_expense': total_expense,
        'title': 'Expense Head Report'
    }

    return render(request,'reports/expense_head_report.html',context)
    
    
@login_required
def expense_head_detail_report(request, pk):

    role = getattr(
        getattr(request.user, 'profile', None),
        'role',
        None
    )

    role_name = role.name if role else None

    if role_name == 'COMPANY_ADMIN':

        company = request.user.profile.company

    else:

        branch = request.user.managed_branch
        company = branch.company

    expense_head = get_object_or_404(
        ExpenseHead,
        pk=pk,
        company=company,
        is_deleted=False
    )

   
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    branch_id = request.GET.get('branch')

    try:
        if from_date:
            from_date = datetime.strptime(
                from_date,
                '%Y-%m-%d'
            ).date()
    except:
        from_date = None

    try:
        if to_date:
            to_date = datetime.strptime(
                to_date,
                '%Y-%m-%d'
            ).date()
    except:
        to_date = None

    expenses = ExpenseEntry.objects.filter(
        is_deleted=False,
        expense__expense_head=expense_head
    ).select_related(
        'expense',
        'branch'
    ).order_by('-expense_date')

    branches = None

    if role_name == 'COMPANY_ADMIN':

        company = request.user.profile.company

        expenses = expenses.filter(
            company=company
        )

        branches = Branch.objects.filter(
            company=company,
            is_deleted=False
        )

    else:

        branch = request.user.managed_branch

        expenses = expenses.filter(
            branch=branch
        )

    if from_date:

        expenses = expenses.filter(
            expense_date__gte=from_date
        )

    if to_date:

        expenses = expenses.filter(
            expense_date__lte=to_date
        )

    if branch_id:

        expenses = expenses.filter(
            branch_id=branch_id
        )

    total_expense = expenses.aggregate(
        total=Sum('amount')
    )['total'] or 0

    context = {

        'expense_head': expense_head,

        'expenses': expenses,

        'total_expense': total_expense,

        'from_date': from_date,
        'to_date': to_date,

        'branches': branches,
        'branch_id': branch_id,

    }

    return render(request,'reports/expense_head_detail_report.html',context)


def generate_invoice_pdf_file(invoice, base_url):
    import sys
    import os
    from django.template.loader import render_to_string
    from django.conf import settings
    
    if sys.platform == 'darwin':
        os.environ['DYLD_FALLBACK_LIBRARY_PATH'] = '/opt/homebrew/lib:' + os.environ.get('DYLD_FALLBACK_LIBRARY_PATH', '')
    from weasyprint import HTML
    
    balance = invoice.total - invoice.amount_collected
    currency = '₹'
    if invoice.branch and invoice.branch.company and invoice.branch.company.country:
        currency = getattr(invoice.branch.company.country, 'currency_symbol', '₹') or '₹'
        
    receipt = invoice.receipts.filter(is_deleted=False).order_by('-date_added').first()
    payment_mode = ''
    if receipt:
        payment_mode = dict(Receipt.PAYMENT_CHOICES).get(receipt.payment_mode, receipt.payment_mode.replace('_', ' ').title())
    elif invoice.invoice_type == 'creditinvoice':
        payment_mode = 'Credit'
    elif invoice.invoice_type == 'cashinvoice':
        payment_mode = 'Cash'

    company_trn = ''
    if invoice.branch:
        if invoice.branch.gst_number:
            company_trn = invoice.branch.gst_number
        elif invoice.branch.company:
            company_trn = invoice.branch.company.gst_number or invoice.branch.company.tin_pan_no or ''
    elif invoice.customer and invoice.customer.company:
        company_trn = invoice.customer.company.gst_number or invoice.customer.company.tin_pan_no or ''

    import re
    if company_trn:
        company_trn = re.sub(r'^(TRN\s*:\s*|TRN\s*|-|:\s*)', '', str(company_trn).strip(), flags=re.IGNORECASE).strip()

    clean_branch_address = ''
    if invoice.branch and invoice.branch.address:
        lines = []
        for line in invoice.branch.address.splitlines():
            if re.search(r'\bTRN\b|\bGSTIN?\b', line, re.IGNORECASE):
                continue
            lines.append(line)
        clean_branch_address = '\n'.join(lines).strip()

    customisation = None
    if invoice.branch and hasattr(invoice.branch, 'invoice_customisation'):
        customisation = invoice.branch.invoice_customisation

    context = {
        'invoice': invoice,
        'balance': balance,
        'currency': currency,
        'payment_mode': payment_mode,
        'company_trn': company_trn,
        'clean_branch_address': clean_branch_address,
        'customisation': customisation,
    }
    
    html_string = render_to_string('invoice/invoice_pdf.html', context)
    
    media_dir = os.path.join(settings.BASE_DIR, 'media', 'invoices')
    os.makedirs(media_dir, exist_ok=True)
    
    clean_no = str(invoice.invoice_number).replace('/', '_')
    pdf_filename = f"invoice-{clean_no}.pdf"
    pdf_path = os.path.join(media_dir, pdf_filename)
    
    # Render PDF using WeasyPrint
    html = HTML(string=html_string, base_url=base_url)
    html.write_pdf(target=pdf_path)

    # Also save with raw filename if it does not contain slashes and differs
    raw_filename = f"invoice-{invoice.invoice_number}.pdf"
    if '/' not in str(invoice.invoice_number):
        raw_pdf_path = os.path.join(media_dir, raw_filename)
        if raw_pdf_path != pdf_path:
            try:
                import shutil
                shutil.copyfile(pdf_path, raw_pdf_path)
            except Exception:
                pass
    
    # Return the absolute public URL
    if not base_url or '127.0.0.1' in base_url or 'localhost' in base_url:
        base_url = 'http://68.183.94.11:78'

    if not base_url.endswith('/'):
        base_url += '/'
    return f"{base_url}media/invoices/{pdf_filename}"


@login_required
def invoice_whatsapp_share(request, pk):
    from finance_management.models import Invoice
    from booking_management.api_views import clean_whatsapp_number
    import urllib.parse

    invoice = get_object_or_404(
        Invoice.objects.select_related('customer', 'vehicle', 'branch', 'branch__company', 'branch__company__country').prefetch_related('items'),
        pk=pk,
        is_deleted=False
    )
    customer = invoice.customer
    phone = (customer.whatsapp_number or customer.phone or '').strip() if customer else ''
    cleaned_phone = clean_whatsapp_number(phone) if phone else ''

    base_url = request.build_absolute_uri('/')
    if not base_url or '127.0.0.1' in base_url or 'localhost' in base_url:
        base_url = 'http://68.183.94.11:78'

    pdf_url = ''
    try:
        pdf_url = generate_invoice_pdf_file(invoice, base_url)
    except Exception:
        clean_no = str(invoice.invoice_number).replace('/', '_')
        pdf_url = f"{base_url.rstrip('/')}/media/invoices/invoice-{clean_no}.pdf"

    company_name = invoice.branch.company.company_name if (invoice.branch and invoice.branch.company) else "Wash Pilot"
    currency = '₹'
    if invoice.branch and invoice.branch.company and invoice.branch.company.country:
        currency = getattr(invoice.branch.company.country, 'currency_symbol', '₹') or '₹'

    branch_name = invoice.branch.name if invoice.branch else company_name

    items_list = []
    for itm in invoice.items.filter(is_operational=False):
        qty_str = f" (x{int(itm.qty)})" if itm.qty and itm.qty > 1 else ""
        item_amt = itm.net_taxable_amount if (itm.net_taxable_amount is not None and itm.net_taxable_amount > 0) else (float(itm.rate or 0) * float(itm.qty or 1))
        items_list.append(f"• {itm.service_name}{qty_str}: {currency}{item_amt:.2f}")
    services_text = "\n".join(items_list)

    inv_type = "Tax Invoice" if invoice.tax_amount and invoice.tax_amount > 0 else "Invoice"
    cust_name = customer.name if customer else "Customer"
    veh_no = invoice.vehicle.vehicle_number if invoice.vehicle else "N/A"
    inv_date = invoice.date.strftime('%d-%b-%Y') if invoice.date else ""

    msg_lines = [
        f"📄 *{inv_type} #{invoice.invoice_number}*",
        f"Dear *{cust_name}*,",
        f"Thank you for visiting *{company_name}* ({branch_name})!",
        f"🚗 Vehicle: *{veh_no}* | 📅 Date: *{inv_date}*",
        f"💰 Total Amount: *{currency}{total_val:.2f}* | ✅ Paid: *{currency}{paid_val:.2f}*",
    ]
    if balance_val > 0:
        msg_lines.append(f"⏳ Balance Due: *{currency}{balance_val:.2f}*")

    if pdf_url:
        msg_lines.extend([
            "",
            "📥 *Click to View & Download Invoice PDF:*",
            pdf_url
        ])

    msg_lines.extend([
        "",
        "Have a smooth and safe drive! 🚗✨"
    ])

    message_text = "\n".join(msg_lines)
    encoded_message = urllib.parse.quote(message_text)

    whatsapp_url = f"https://api.whatsapp.com/send?phone={cleaned_phone}&text={encoded_message}"

    # Trigger background official API message if client has active credentials
    try:
        from client_management.api_views import send_invoice_whatsapp_background
        import threading
        threading.Thread(
            target=send_invoice_whatsapp_background,
            args=(str(invoice.id), base_url),
            daemon=True
        ).start()
    except Exception:
        pass

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('format') == 'json':
        return JsonResponse({
            'success': True,
            'whatsapp_url': whatsapp_url,
            'phone': cleaned_phone,
            'customer_name': cust_name,
            'invoice_number': invoice.invoice_number,
            'message': message_text,
            'pdf_url': pdf_url
        })

    return redirect(whatsapp_url)


def invoice_pdf_view(request, pk):
    from finance_management.models import Invoice
    invoice = get_object_or_404(Invoice, pk=pk, is_deleted=False)
    base_url = request.build_absolute_uri('/')
    if not base_url or '127.0.0.1' in base_url or 'localhost' in base_url:
        base_url = 'http://68.183.94.11:78'
    pdf_url = generate_invoice_pdf_file(invoice, base_url)
    return redirect(pdf_url)


@login_required
def credit_note_receipt(request, pk):
    from finance_management.models import CreditNote
    from decimal import Decimal
    credit_note = get_object_or_404(
        CreditNote.objects.select_related(
            'invoice', 'invoice__vehicle', 'invoice__vehicle__vehicle_type_model', 'branch', 'branch__company', 'customer'
        ).prefetch_related('items'),
        pk=pk,
        is_deleted=False
    )

    currency = '₹'
    if credit_note.branch and credit_note.branch.company and credit_note.branch.company.country:
        currency = getattr(credit_note.branch.company.country, 'currency_symbol', '₹') or '₹'

    company_trn = ''
    if credit_note.branch:
        if credit_note.branch.gst_number:
            company_trn = credit_note.branch.gst_number
        elif credit_note.branch.company:
            company_trn = credit_note.branch.company.gst_number or credit_note.branch.company.tin_pan_no or ''

    credited_so_far = credit_note.invoice.credit_note_amount or Decimal('0.00')
    remaining_balance = max(Decimal('0.00'), credit_note.invoice.total - credit_note.invoice.amount_collected - credited_so_far)

    context = {
        'credit_note': credit_note,
        'currency': currency,
        'company_trn': company_trn,
        'remaining_balance': remaining_balance,
    }
    return render(request, 'credit_note/receipt.html', context)


def generate_credit_note_pdf_file(credit_note, base_url):
    import sys
    import os
    from django.template.loader import render_to_string
    from django.conf import settings
    from decimal import Decimal

    if sys.platform == 'darwin':
        os.environ['DYLD_FALLBACK_LIBRARY_PATH'] = '/opt/homebrew/lib:' + os.environ.get('DYLD_FALLBACK_LIBRARY_PATH', '')
    from weasyprint import HTML

    currency = '₹'
    if credit_note.branch and credit_note.branch.company and credit_note.branch.company.country:
        currency = getattr(credit_note.branch.company.country, 'currency_symbol', '₹') or '₹'

    company_trn = ''
    if credit_note.branch:
        if credit_note.branch.gst_number:
            company_trn = credit_note.branch.gst_number
        elif credit_note.branch.company:
            company_trn = credit_note.branch.company.gst_number or credit_note.branch.company.tin_pan_no or ''

    credited_so_far = credit_note.invoice.credit_note_amount or Decimal('0.00')
    remaining_balance = max(Decimal('0.00'), credit_note.invoice.total - credit_note.invoice.amount_collected - credited_so_far)

    context = {
        'credit_note': credit_note,
        'currency': currency,
        'company_trn': company_trn,
        'remaining_balance': remaining_balance,
    }
    html_string = render_to_string('credit_note/receipt.html', context)

    media_dir = os.path.join(settings.BASE_DIR, 'media', 'credit_notes')
    os.makedirs(media_dir, exist_ok=True)

    clean_no = str(credit_note.credit_note_number).replace('/', '_')
    pdf_filename = f"creditnote-{clean_no}.pdf"
    pdf_path = os.path.join(media_dir, pdf_filename)

    html = HTML(string=html_string, base_url=base_url)
    html.write_pdf(target=pdf_path)

    if not base_url or '127.0.0.1' in base_url or 'localhost' in base_url:
        base_url = 'http://68.183.94.11:78'

    if not base_url.endswith('/'):
        base_url += '/'
    return f"{base_url}media/credit_notes/{pdf_filename}"


@login_required
def credit_note_pdf_view(request, pk):
    from finance_management.models import CreditNote
    credit_note = get_object_or_404(CreditNote, pk=pk, is_deleted=False)
    base_url = request.build_absolute_uri('/')
    if not base_url or '127.0.0.1' in base_url or 'localhost' in base_url:
        base_url = 'http://68.183.94.11:78'
    pdf_url = generate_credit_note_pdf_file(credit_note, base_url)
    return redirect(pdf_url)


@login_required
def credit_note_whatsapp_share(request, pk):
    from finance_management.models import CreditNote
    from booking_management.api_views import clean_whatsapp_number
    import urllib.parse

    credit_note = get_object_or_404(
        CreditNote.objects.select_related('customer', 'branch', 'branch__company', 'invoice', 'invoice__vehicle'),
        pk=pk,
        is_deleted=False
    )
    customer = credit_note.customer
    phone = (customer.whatsapp_number or customer.phone or '').strip() if customer else ''
    cleaned_phone = clean_whatsapp_number(phone) if phone else ''

    base_url = request.build_absolute_uri('/')
    if not base_url or '127.0.0.1' in base_url or 'localhost' in base_url:
        base_url = 'http://68.183.94.11:78'

    pdf_url = ''
    try:
        pdf_url = generate_credit_note_pdf_file(credit_note, base_url)
    except Exception:
        clean_no = str(credit_note.credit_note_number).replace('/', '_')
        pdf_url = f"{base_url.rstrip('/')}/media/credit_notes/creditnote-{clean_no}.pdf"

    company_name = credit_note.branch.company.company_name if (credit_note.branch and credit_note.branch.company) else "Wash Pilot"
    currency = '₹'
    if credit_note.branch and credit_note.branch.company and credit_note.branch.company.country:
        currency = getattr(credit_note.branch.company.country, 'currency_symbol', '₹') or '₹'

    branch_name = credit_note.branch.name if credit_note.branch else company_name

    msg_lines = [
        f"Dear *{customer.name if customer else 'Customer'}*,",
        f"A Credit Note has been issued for your reference at *{company_name}* ({branch_name}).",
        "",
        f"📝 *Credit Note No:* {credit_note.credit_note_number}",
        f"📄 *Ref. Invoice:* {credit_note.invoice.invoice_number if credit_note.invoice else 'N/A'}",
        f"📅 *Date:* {credit_note.date.strftime('%d-%b-%Y') if credit_note.date else ''}",
        f"💰 *Credited Amount:* -{currency}{credit_note.total:.2f}",
        f"📌 *Reason:* {credit_note.reason or 'Adjustment'}",
    ]
    if credit_note.remarks:
        msg_lines.append(f"💬 *Remarks:* {credit_note.remarks}")

    if pdf_url:
        msg_lines.extend([
            "",
            "📄 *Download Credit Note PDF:*",
            pdf_url
        ])

    msg_lines.extend([
        "",
        f"Thank you for choosing *{company_name}*!"
    ])

    message_text = "\n".join(msg_lines)
    encoded_message = urllib.parse.quote(message_text)

    whatsapp_url = f"https://api.whatsapp.com/send?phone={cleaned_phone}&text={encoded_message}"

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('format') == 'json':
        return JsonResponse({
            'success': True,
            'whatsapp_url': whatsapp_url,
            'phone': cleaned_phone,
            'credit_note_number': credit_note.credit_note_number,
            'message': message_text,
            'pdf_url': pdf_url
        })

    return redirect(whatsapp_url)


def generate_quotation_pdf_file(quotation, base_url, overwrite=True):
    import sys
    import os
    from django.template.loader import render_to_string
    from django.conf import settings

    media_dir = os.path.join(settings.BASE_DIR, 'media', 'quotations')
    os.makedirs(media_dir, exist_ok=True)
    
    clean_no = str(quotation.quotation_number).replace('/', '_')
    pdf_filename = f"quotation-{clean_no}.pdf"
    pdf_path = os.path.join(media_dir, pdf_filename)

    if not overwrite and os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
        if not base_url or '127.0.0.1' in base_url or 'localhost' in base_url:
            base_url = 'http://68.183.94.11:78'
        if not base_url.endswith('/'):
            base_url += '/'
        return f"{base_url}media/quotations/{pdf_filename}"
    
    if sys.platform == 'darwin':
        os.environ['DYLD_FALLBACK_LIBRARY_PATH'] = '/opt/homebrew/lib:' + os.environ.get('DYLD_FALLBACK_LIBRARY_PATH', '')
    from weasyprint import HTML
    
    currency = '₹'
    company = None
    if quotation.branch and quotation.branch.company:
        company = quotation.branch.company
    elif hasattr(quotation, 'customer') and quotation.customer and quotation.customer.company:
        company = quotation.customer.company

    if company and company.country:
        currency = getattr(company.country, 'currency_symbol', '₹') or '₹'

    # Company logo handling with local absolute path or url fallback
    company_logo = None
    if company:
        logo_field = getattr(company, 'logo_color', None) or getattr(company, 'logo_bw', None) or getattr(company, 'logo', None)
        if logo_field:
            try:
                if hasattr(logo_field, 'path') and os.path.exists(logo_field.path):
                    company_logo = 'file://' + os.path.abspath(logo_field.path)
                elif hasattr(logo_field, 'url'):
                    company_logo = logo_field.url
            except Exception:
                company_logo = getattr(logo_field, 'url', None)
    if not company_logo and quotation.branch and getattr(quotation.branch, 'logo', None):
        try:
            if hasattr(quotation.branch.logo, 'path') and os.path.exists(quotation.branch.logo.path):
                company_logo = 'file://' + os.path.abspath(quotation.branch.logo.path)
            elif hasattr(quotation.branch.logo, 'url'):
                company_logo = quotation.branch.logo.url
        except Exception:
            company_logo = getattr(quotation.branch.logo, 'url', None)

    services = []
    accessories = []
    labour = []
    extras_list = []

    # 1. Check reported issues (JobQuotation)
    handled_priced_item_ids = set()
    if hasattr(quotation, 'reported_issues'):
        for issue in quotation.reported_issues.filter(is_deleted=False).select_related('category', 'service'):
            priced = getattr(issue, 'priced_item', None)
            rate = 0.0
            qty = 1.0
            disc = 0.0
            total = 0.0
            if priced and not priced.is_deleted:
                handled_priced_item_ids.add(priced.id)
                rate = float(priced.rate or 0)
                qty = float(priced.quantity or 1)
                disc = float(priced.discount or 0)
                total = max(0.0, (rate * qty) - disc)

            services.append({
                'name': issue.service.name if issue.service else 'Service',
                'category': issue.category.name if issue.category else '',
                'issue_text': issue.issue_text or '',
                'warranty': '',
                'quantity': qty,
                'rate': rate,
                'discount': disc,
                'total': total,
                'remarks': '',
            })

    # 2. Check quotation items (Accessories, standalone Services/Issues, or legacy items)
    if hasattr(quotation, 'items'):
        for item in quotation.items.filter(is_deleted=False).select_related('stock_item', 'service'):
            if item.id in handled_priced_item_ids:
                continue
            if getattr(item, 'reported_issue_id', None) or getattr(item, 'line_type', None) == 'issue':
                continue
            line_type = getattr(item, 'line_type', None)
            rate = float(item.rate or 0)
            qty = float(item.quantity or 1)
            disc = float(getattr(item, 'discount', 0) or 0)
            total = max(0.0, (rate * qty) - disc)
            warranty = f"{item.warranty_years} yrs" if (item.warranty_years and item.warranty_years > 0) else ''

            if line_type == 'accessory':
                name = item.stock_item_name or (item.stock_item.name if item.stock_item else item.service_name)
                part_no = ''
                if item.stock_item:
                    part_no = getattr(item.stock_item, 'part_number', '') or getattr(item.stock_item, 'product_code', '') or ''
                if not part_no:
                    part_no = getattr(item, 'part_number', '') or ''
                accessories.append({
                    'name': name,
                    'part_number': part_no,
                    'warranty': warranty,
                    'quantity': qty,
                    'rate': rate,
                    'discount': disc,
                    'total': total,
                    'remarks': getattr(item, 'remarks', '') or '',
                    'free_topup': getattr(item, 'free_topup', '') or '',
                })
            else:
                s_name = item.service_name or (item.service.name if item.service else 'Service')
                already = any(s.get('name') == s_name for s in services)
                if not already:
                    services.append({
                        'name': s_name,
                        'category': '',
                        'issue_text': item.stock_item_name or getattr(item, 'remarks', '') or '',
                        'warranty': warranty,
                        'quantity': qty,
                        'rate': rate,
                        'discount': disc,
                        'total': total,
                        'remarks': getattr(item, 'remarks', '') or '',
                    })

    # 3. Check quotation extras (Labour Charges vs Custom Extras)
    if hasattr(quotation, 'extras'):
        for extra in quotation.extras.filter(is_deleted=False):
            line_type = getattr(extra, 'line_type', None)
            rate = float(extra.price or 0)
            qty = float(extra.quantity or 1)
            disc = float(extra.discount or 0)
            total = float(extra.total or max(0.0, (rate * qty) - disc))

            if line_type == 'labour':
                labour.append({
                    'name': extra.name,
                    'quantity': qty,
                    'rate': rate,
                    'discount': disc,
                    'total': total,
                    'remarks': extra.remarks or '',
                })
            else:
                extras_list.append({
                    'name': extra.name,
                    'quantity': qty,
                    'rate': rate,
                    'discount': disc,
                    'total': total,
                    'remarks': extra.remarks or '',
                })

    services_subtotal = sum(s['total'] for s in services)
    accessories_subtotal = sum(a['total'] for a in accessories)
    labour_subtotal = sum(l['total'] for l in labour)
    extras_subtotal = sum(e['total'] for e in extras_list)
    calc_subtotal = services_subtotal + accessories_subtotal + labour_subtotal + extras_subtotal

    subtotal = float(quotation.subtotal) if quotation.subtotal else calc_subtotal
    discount = float(quotation.discount or 0)
    tax_percentage = float(quotation.tax_percentage or 0)
    tax_amount = float(quotation.tax_amount or 0)

    if tax_percentage == 0 and tax_amount == 0 and company:
        from tax_management.models import CompanyTax
        enabled_taxes = CompanyTax.objects.filter(company=company, is_enabled=True, is_deleted=False).select_related('tax')
        if enabled_taxes.exists():
            tax_percentage = sum(float(ct.tax.percent) for ct in enabled_taxes)
            taxable = max(0.0, subtotal - discount)
            tax_amount = round(taxable * (tax_percentage / 100.0), 2)

    grand_total = float(quotation.grand_total) if (quotation.grand_total and (tax_amount == 0 or float(quotation.grand_total) > (subtotal - discount))) else round(max(0.0, subtotal - discount) + tax_amount, 2)

    # 4. Inspection details & checklist
    raw_inspection = getattr(quotation, 'inspection_details', None) or {}
    if not isinstance(raw_inspection, dict):
        raw_inspection = {}

    damage_marks = raw_inspection.get('damage_marks') or []
    damage_marks_count = len(damage_marks) if isinstance(damage_marks, list) else 0

    checklist_raw = raw_inspection.get('checklist') or {}
    checklist_items = []
    if isinstance(checklist_raw, dict) and checklist_raw:
        from service_management.models import InspectionItem
        item_ids = [k for k in checklist_raw.keys()]
        db_items = {}
        try:
            db_items = {str(item.id): item for item in InspectionItem.objects.filter(id__in=item_ids).select_related('category')}
        except Exception:
            pass

        for k, v in checklist_raw.items():
            if isinstance(v, dict):
                obj = db_items.get(str(k))
                item_name = v.get('name') or (obj.name if obj else str(k))
                category_name = v.get('category') or (obj.category.name if obj and obj.category else '')
                status = (v.get('status') or '').strip().lower()
                value = v.get('value') or ''
                remarks = v.get('remarks') or ''
                if status or value or remarks:
                    status_display = status.upper()
                    if status == 'pass':
                        status_display = 'PASS'
                    elif status == 'good':
                        status_display = 'GOOD'
                    elif status == 'attention':
                        status_display = 'ATTENTION'
                    elif status == 'fail':
                        status_display = 'FAIL'
                    elif status == 'critical':
                        status_display = 'CRITICAL'
                    checklist_items.append({
                        'name': item_name,
                        'category': category_name,
                        'status': status,
                        'status_display': status_display,
                        'value': value,
                        'remarks': remarks,
                    })

    tyre = raw_inspection.get('tyre') if isinstance(raw_inspection.get('tyre'), dict) else {}
    oil = raw_inspection.get('oil_service') or raw_inspection.get('oil') or {}
    if not isinstance(oil, dict):
        oil = {}
    brake = raw_inspection.get('brake_service') if isinstance(raw_inspection.get('brake_service'), dict) else {}
    wheel_alignment = raw_inspection.get('wheel_alignment') if isinstance(raw_inspection.get('wheel_alignment'), dict) else {}

    has_inspection = bool(
        checklist_items or damage_marks_count > 0 or tyre or oil or brake or wheel_alignment or getattr(quotation, 'inspection_at', None)
    )

    company_seal = None
    if company and getattr(company, 'company_seal', None):
        try:
            seal_field = company.company_seal
            if hasattr(seal_field, 'path') and os.path.exists(seal_field.path):
                company_seal = 'file://' + os.path.abspath(seal_field.path)
            elif hasattr(seal_field, 'url'):
                company_seal = seal_field.url
        except Exception:
            company_seal = getattr(company.company_seal, 'url', None)

    prepared_by_name = ''
    if getattr(quotation, 'prepared_by', None):
        prepared_by_name = getattr(quotation.prepared_by, 'name', '') or str(quotation.prepared_by)
    elif getattr(quotation, 'prepared_by_id', None):
        prepared_by_name = str(quotation.prepared_by_id)

    days_needed_text = ''
    if getattr(quotation, 'additional_days_needed', 0):
        days_needed_text = f"{quotation.additional_days_needed} Days"

    comp_name = company.company_name if company else 'Auto Care'
    br_name = quotation.branch.name if quotation.branch else ''

    context = {
        'quotation': quotation,
        'company': company,
        'company_name': comp_name,
        'branch_name': br_name,
        'company_logo': company_logo,
        'currency': currency,
        'services': services,
        'accessories': accessories,
        'labour': labour,
        'extras': extras_list,
        'services_subtotal': services_subtotal,
        'accessories_subtotal': accessories_subtotal,
        'labour_subtotal': labour_subtotal,
        'extras_subtotal': extras_subtotal,
        'subtotal': subtotal,
        'discount': discount,
        'tax_percentage': tax_percentage,
        'tax_amount': tax_amount,
        'grand_total': grand_total,
        'has_inspection': has_inspection,
        'damage_marks': damage_marks,
        'damage_marks_count': damage_marks_count,
        'checklist_items': checklist_items,
        'tyre_inspection': tyre,
        'oil_inspection': oil,
        'brake_inspection': brake,
        'wheel_alignment_inspection': wheel_alignment,
        'company_seal': company_seal,
        'prepared_by_name': prepared_by_name,
        'days_needed': days_needed_text,
    }
    
    html_string = render_to_string('quotation/quotation_pdf.html', context)
    
    media_dir = os.path.join(settings.BASE_DIR, 'media', 'quotations')
    os.makedirs(media_dir, exist_ok=True)
    
    clean_no = str(quotation.quotation_number).replace('/', '_')
    pdf_filename = f"quotation-{clean_no}.pdf"
    pdf_path = os.path.join(media_dir, pdf_filename)
    
    html = HTML(string=html_string, base_url=base_url)
    html.write_pdf(target=pdf_path)
    
    if not base_url or '127.0.0.1' in base_url or 'localhost' in base_url:
        base_url = 'http://68.183.94.11:78'

    if not base_url.endswith('/'):
        base_url += '/'
    return f"{base_url}media/quotations/{pdf_filename}"


@login_required
def payment_type_report(request):
    user = request.user
    role = user.profile.role.name if hasattr(user, 'profile') and user.profile.role else None

    from finance_management.models import Receipt
    from django.db.models import Sum

    receipts = Receipt.objects.filter(is_deleted=False).select_related(
        'invoice', 'invoice__customer', 'invoice__vehicle', 'invoice__branch'
    ).order_by('-created_at')

    # Scope filtering
    if role == 'COMPANY_ADMIN' and hasattr(user.profile, 'company') and user.profile.company:
        receipts = receipts.filter(invoice__branch__company=user.profile.company)
        branches = Branch.objects.filter(company=user.profile.company, is_deleted=False)
    elif role == 'BRANCH_ADMIN' and hasattr(user, 'managed_branch') and user.managed_branch:
        receipts = receipts.filter(invoice__branch=user.managed_branch)
        branches = None
    else:
        branches = Branch.objects.filter(is_deleted=False)

    # Date filters
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    branch_id = request.GET.get('branch_id')

    if from_date:
        receipts = receipts.filter(created_at__date__gte=from_date)
    if to_date:
        receipts = receipts.filter(created_at__date__lte=to_date)
    if branch_id:
        receipts = receipts.filter(invoice__branch_id=branch_id)

    # Calculate payment type totals
    grouped = receipts.values('payment_mode').annotate(total_amount=Sum('amount')).order_by('-total_amount')
    
    PAYMENT_LABELS = dict(Receipt.PAYMENT_CHOICES)
    summary = []
    total_collected = 0
    for item in grouped:
        mode = item['payment_mode']
        amt = item['total_amount'] or 0
        total_collected += amt
        summary.append({
            'payment_mode': mode,
            'payment_mode_display': PAYMENT_LABELS.get(mode, mode.title()),
            'total_amount': amt,
        })

    # Fill in missing modes
    existing_modes = {item['payment_mode'] for item in grouped}
    for mode, label in Receipt.PAYMENT_CHOICES:
        if mode not in existing_modes:
            summary.append({
                'payment_mode': mode,
                'payment_mode_display': label,
                'total_amount': Decimal('0.00'),
            })

    context = {
        'receipts': receipts,
        'summary': summary,
        'total_collected': total_collected,
        'branches': branches,
        'from_date': from_date,
        'to_date': to_date,
        'branch_id': branch_id,
        'title': 'Payment Type Report',
    }

    return render(request, 'reports/payment_type_report.html', context)


@login_required
def staff_income_report(request):
    user = request.user
    role = user.profile.role.name if hasattr(user, 'profile') and user.profile.role else None

    from client_management.models import Branch, Staff
    from finance_management.models import Invoice
    from datetime import datetime, date

    from_date_str = request.GET.get('from_date', '')
    to_date_str = request.GET.get('to_date', '')
    branch_id = request.GET.get('branch_id', '')
    staff_id = request.GET.get('staff_id', '')

    today = date.today()
    def parse_d(d_str, default):
        if not d_str:
            return default
        try:
            return datetime.strptime(d_str, '%Y-%m-%d').date()
        except ValueError:
            try:
                return datetime.strptime(d_str, '%d-%m-%Y').date()
            except ValueError:
                return default

    from_date = parse_d(from_date_str, today)
    to_date = parse_d(to_date_str, today)


    invoices = Invoice.objects.filter(
        is_deleted=False,
        date__gte=from_date,
        date__lte=to_date,
        assigned_staffs__isnull=False
    ).prefetch_related('assigned_staffs', 'customer', 'vehicle', 'branch').distinct()

    staff_qs = Staff.objects.filter(is_deleted=False)
    branches = None

    if role == 'COMPANY_ADMIN':
        if hasattr(user.profile, 'company') and user.profile.company:
            company = user.profile.company
            invoices = invoices.filter(branch__company=company)
            staff_qs = staff_qs.filter(company=company)
            branches = Branch.objects.filter(company=company, is_deleted=False)
        else:
            branches = Branch.objects.filter(is_deleted=False)
    elif role == 'BRANCH_ADMIN':
        if hasattr(user, 'managed_branch') and user.managed_branch:
            invoices = invoices.filter(branch=user.managed_branch)
            staff_qs = staff_qs.filter(branch=user.managed_branch)
        branches = None

    if branch_id:
        invoices = invoices.filter(branch_id=branch_id)
        staff_qs = staff_qs.filter(branch_id=branch_id)

    if staff_id:
        invoices = invoices.filter(assigned_staffs__id=staff_id)
        staff_qs = staff_qs.filter(id=staff_id)

    staff_map = {}
    for st in staff_qs:
        desig = st.get_designation_display() if hasattr(st, 'get_designation_display') else (st.designation or '')
        staff_map[str(st.id)] = {
            'id': str(st.id),
            'name': st.name,
            'employee_id': st.employee_id or '',
            'designation': desig,
            'branch_name': st.branch.name if st.branch else '',
            'invoice_count': 0,
            'total_income': 0.0,
            'split_income': 0.0,
            'invoices': [],
        }

    total_invoices_set = set()

    for inv in invoices.order_by('-date', '-auto_id'):
        assigned = list(inv.assigned_staffs.all())
        if not assigned:
            continue

        total_invoices_set.add(inv.id)
        staff_count = len(assigned)
        inv_total = float(inv.total or 0.0)
        split_share = inv_total / staff_count if staff_count > 0 else 0.0

        for st in assigned:
            st_id = str(st.id)
            if st_id not in staff_map:
                desig = st.get_designation_display() if hasattr(st, 'get_designation_display') else (st.designation or '')
                staff_map[st_id] = {
                    'id': st_id,
                    'name': st.name,
                    'employee_id': st.employee_id or '',
                    'designation': desig,
                    'branch_name': st.branch.name if st.branch else '',
                    'invoice_count': 0,
                    'total_income': 0.0,
                    'split_income': 0.0,
                    'invoices': [],
                }

            sdata = staff_map[st_id]
            sdata['invoice_count'] += 1
            sdata['total_income'] += inv_total
            sdata['split_income'] += split_share
            sdata['invoices'].append({
                'id': str(inv.id),
                'invoice_number': inv.invoice_number,
                'date': inv.date,
                'customer_name': inv.customer.name if inv.customer else 'N/A',
                'vehicle_number': inv.vehicle.vehicle_number if inv.vehicle else 'N/A',
                'total': inv_total,
                'assigned_staff_count': staff_count,
                'share_amount': split_share,
            })

    staff_rows = sorted(list(staff_map.values()), key=lambda x: x['total_income'], reverse=True)

    grand_total_income = sum(float(inv.total or 0.0) for inv in invoices)
    grand_split_income = sum(r['split_income'] for r in staff_rows)

    context = {
        'from_date': from_date.strftime('%Y-%m-%d'),
        'to_date': to_date.strftime('%Y-%m-%d'),
        'branch_id': branch_id,
        'staff_id': staff_id,
        'branches': branches,
        'all_staffs': staff_qs,
        'staff_rows': staff_rows,
        'total_staffs': len(staff_rows),
        'total_invoices': len(total_invoices_set),
        'grand_total_income': grand_total_income,
        'grand_split_income': grand_split_income,
        'title': 'Staff Income Report',
    }

    return render(request, 'reports/staff_income_report.html', context)


@login_required

def ajax_get_customer_vehicles(request, customer_id):
    from client_management.models import CustomerVehicle
    vehicles = CustomerVehicle.objects.filter(customer_id=customer_id, is_deleted=False).select_related('vehicle_type_model')
    data = []
    for v in vehicles:
        data.append({
            'id': str(v.id),
            'vehicle_number': v.vehicle_number,
            'model_name': v.vehicle_type_model.name if v.vehicle_type_model else '',
            'wheel_type': v.wheel_type or 'normal_wheel',
            'current_odometer_km': v.current_odometer_km or 0,
        })
    return JsonResponse({'success': True, 'vehicles': data})


@login_required
def invoice_create(request):
    user = request.user
    role = user.profile.role.name if hasattr(user, 'profile') and user.profile.role else None

    if request.method == 'POST':
        import json
        if request.content_type == 'application/json':
            data = json.loads(request.body)
        else:
            payload_str = request.POST.get('payload')
            if payload_str:
                data = json.loads(payload_str)
            else:
                data = request.POST.dict()

        customer_id = data.get('customer_id')
        vehicle_id = data.get('vehicle_id')
        is_direct_sale = bool(data.get('is_direct_sale', False))
        
        if not customer_id and not data.get('customer_phone') and not data.get('phone'):
            return JsonResponse({'success': False, 'message': 'Customer is required'}, status=400)
        if not is_direct_sale and not vehicle_id:
            return JsonResponse({'success': False, 'message': 'Vehicle is required'}, status=400)

        from client_management.api_views import api_create_invoice
        request._body = json.dumps(data).encode('utf-8')
        response = api_create_invoice(request)
        return response

    from client_management.models import Customer, Stock, Scheme, Extra, Branch, CustomerType, Staff
    from tax_management.models import CompanyTax
    from service_management.models import Service
    from master.models import (Country, OilProduct, OilFilter, TyreBrand, Tyre, Battery,
                               VehicleType, VehicleTypeModel, VehicleMake, VehicleBrandModel,
                               VehicleColor, EmissionStandard)
    from django.db.models import Q

    company = getattr(user.profile, 'company', None) if hasattr(user, 'profile') else None
    managed_branch = getattr(user, 'managed_branch', None)
    if not company and managed_branch:
        company = managed_branch.company

    branches_qs = Branch.objects.filter(is_deleted=False)
    if role == 'COMPANY_ADMIN' and company:
        branches_qs = branches_qs.filter(company=company).order_by('name')
    elif role == 'BRANCH_ADMIN' and managed_branch:
        branches_qs = branches_qs.filter(id=managed_branch.id)
    elif company:
        branches_qs = branches_qs.filter(company=company).order_by('name')
    else:
        branches_qs = branches_qs.order_by('name')

    selected_branch_id = request.GET.get('branch_id', '')
    if not selected_branch_id:
        if role == 'BRANCH_ADMIN' and managed_branch:
            selected_branch_id = str(managed_branch.id)
        elif branches_qs.exists():
            selected_branch_id = str(branches_qs.first().id)

    selected_customer_id = request.GET.get('customer_id', '')
    selected_vehicle_id = request.GET.get('vehicle_id', '')

    customer_qs = Customer.objects.filter(is_deleted=False).order_by('name')
    service_qs = Service.objects.filter(is_deleted=False).order_by('name')
    stock_qs = Stock.objects.filter(is_deleted=False).order_by('item_name')
    extras_qs = Extra.objects.filter(is_deleted=False).order_by('name')
    scheme_qs = Scheme.objects.filter(is_deleted=False).order_by('name')
    staff_qs = Staff.objects.filter(is_deleted=False).order_by('name')
    customer_types = CustomerType.objects.filter(is_deleted=False).order_by('name')
    vehicle_models = VehicleTypeModel.objects.filter(is_deleted=False).select_related('vehicle_type').order_by('name')
    invoice_vehicle_types = VehicleType.objects.filter(is_active=True, is_deleted=False)
    invoice_vehicle_models = VehicleTypeModel.objects.filter(is_active=True, is_deleted=False).select_related('vehicle_type')
    if company:
        invoice_vehicle_types = invoice_vehicle_types.filter(Q(company=company) | Q(company__isnull=True))
        invoice_vehicle_models = invoice_vehicle_models.filter(Q(company=company) | Q(company__isnull=True)).exclude(disabled_companies=company)
    selected_branch = branches_qs.filter(id=selected_branch_id).first() if selected_branch_id else None
    if selected_branch and selected_branch.enabled_vehicle_types.exists():
        invoice_vehicle_types = invoice_vehicle_types.filter(id__in=selected_branch.enabled_vehicle_types.values('id'))
        invoice_vehicle_models = invoice_vehicle_models.filter(vehicle_type_id__in=selected_branch.enabled_vehicle_types.values('id'))

    if role == 'COMPANY_ADMIN' and company:
        customer_qs = customer_qs.filter(company=company)
        service_qs = service_qs.filter(
            company_service_entries__company=company,
            company_service_entries__is_enabled=True,
        ).distinct()
        stock_qs = stock_qs.filter(company=company)
        extras_qs = extras_qs.filter(company=company)
        scheme_qs = scheme_qs.filter(company=company)
        staff_qs = staff_qs.filter(company=company)
    elif role == 'BRANCH_ADMIN' and managed_branch:
        customer_qs = customer_qs.filter(branch=managed_branch)
        service_qs = service_qs.filter(
            service_branches__branch=managed_branch,
            service_branches__is_enabled=True,
        ).distinct()
        stock_qs = stock_qs.filter(company=managed_branch.company)
        extras_qs = extras_qs.filter(company=managed_branch.company)
        scheme_qs = scheme_qs.filter(company=managed_branch.company)
        staff_qs = staff_qs.filter(branch=managed_branch)

    oil_products = OilProduct.objects.filter(is_deleted=False).order_by('name')
    oil_filters = OilFilter.objects.filter(is_deleted=False).order_by('name')
    tyre_brands = TyreBrand.objects.filter(is_deleted=False).order_by('brand')
    tyres = Tyre.objects.filter(is_deleted=False).select_related('tyre_brand').order_by('name')

    battery_qs = Battery.objects.filter(is_deleted=False, is_active=True).select_related('make', 'ampere', 'segment').order_by('make__name')
    if company:
        battery_qs = battery_qs.filter(Q(company=company) | Q(company__isnull=True))
    
    company_taxes = []
    if company:
        company_taxes = CompanyTax.objects.filter(company=company, is_deleted=False, is_enabled=True).select_related('tax')

    from client_management.models import WhatsAppSetting
    selected_branch_obj = None
    if selected_branch_id:
        selected_branch_obj = branches_qs.filter(id=selected_branch_id).first()
    elif branches_qs.exists():
        selected_branch_obj = branches_qs.first()

    customisation = getattr(selected_branch_obj, 'invoice_customisation', None) if selected_branch_obj else None
    auto_wa_enabled = customisation.send_invoice_via_whatsapp if customisation else False

    whatsapp_invoice_enabled = WhatsAppSetting.objects.filter(
        company=company,
        is_deleted=False,
    ).exclude(username='').exclude(password='').exists() if company else False

    currency_symbol = '₹'
    if company and getattr(company, 'country', None) and getattr(company.country, 'currency_symbol', None):
        currency_symbol = company.country.currency_symbol

    is_uae = False
    country_obj = getattr(company, 'country', None) if company else None
    if not country_obj and hasattr(user, 'profile') and getattr(user.profile, 'company', None):
        country_obj = getattr(user.profile.company, 'country', None)
    if not country_obj and hasattr(user, 'profile') and getattr(user.profile, 'branch', None) and getattr(user.profile.branch, 'company', None):
        country_obj = getattr(user.profile.branch.company, 'country', None)

    if country_obj:
        iso = (country_obj.phone_iso_code or '').strip().upper()
        curr = (country_obj.currency_code or '').strip().upper()
        cname = (country_obj.name or '').strip().lower()
        if iso == 'AE' or curr == 'AED' or 'emirates' in cname or 'uae' in cname:
            is_uae = True

    context = {
        'branches': branches_qs,
        'selected_branch_id': selected_branch_id,
        'selected_customer_id': selected_customer_id,
        'selected_vehicle_id': selected_vehicle_id,
        'user_role': role,
        'is_uae': is_uae,
        'auto_wa_enabled': auto_wa_enabled,
        'whatsapp_invoice_enabled': whatsapp_invoice_enabled,
        'currency_symbol': currency_symbol,
        'customers': customer_qs,
        'services': service_qs,
        'stock_items': stock_qs,
        'extras': extras_qs,
        'schemes': scheme_qs,
        'oil_products': oil_products,
        'oil_filters': oil_filters,
        'tyre_brands': tyre_brands,
        'tyres': tyres,
        'batteries': battery_qs,
        'staff_members': staff_qs,
        'customer_types': customer_types,
        'vehicle_models': vehicle_models,
        'invoice_vehicle_types': invoice_vehicle_types.order_by('name'),
        'invoice_vehicle_models': invoice_vehicle_models.order_by('name'),
        'invoice_vehicle_makes': VehicleMake.objects.filter(is_active=True, is_deleted=False).order_by('name'),
        'invoice_vehicle_brands': VehicleBrandModel.objects.filter(is_active=True, is_deleted=False).select_related('make', 'vehicle_type_model').order_by('name'),
        'invoice_vehicle_colors': VehicleColor.objects.filter(is_deleted=False).order_by('name'),
        'invoice_emission_standards': EmissionStandard.objects.filter(is_deleted=False).order_by('name'),
        'company_taxes': company_taxes,
        'is_tax_inclusive': bool(getattr(company, 'is_tax_inclusive', False)),
        'whatsapp_invoice_enabled': whatsapp_invoice_enabled,
        'phone_countries': Country.objects.filter(is_deleted=False).exclude(phone_dial_code__isnull=True).exclude(phone_dial_code='').order_by('name'),
        'phone_country_iso': (company.country.phone_iso_code if company and company.country and company.country.phone_iso_code else 'IN'),
        'title': 'Create Invoice',
    }

    return render(request, 'invoice/create.html', context)


@login_required
def collection_report(request):
    user = request.user
    role = user.profile.role.name if hasattr(user, 'profile') and user.profile.role else None

    from finance_management.models import Receipt
    from django.db.models import Sum

    today = timezone.localdate() if hasattr(timezone, 'localdate') else timezone.now().date()
    today_str = today.strftime('%Y-%m-%d')

    from_date_param = request.GET.get('from_date') if 'from_date' in request.GET else request.GET.get('fromdate')
    to_date_param = request.GET.get('to_date') if 'to_date' in request.GET else request.GET.get('todate')

    if from_date_param is None:
        from_date = today_str
    else:
        from_date = from_date_param.strip()

    if to_date_param is None:
        to_date = today_str
    else:
        to_date = to_date_param.strip()

    receipts = Receipt.objects.filter(is_deleted=False).select_related(
        'invoice', 'invoice__customer', 'invoice__vehicle', 'invoice__vehicle__vehicle_type_model', 'invoice__branch'
    ).order_by('-created_at')

    branches = None
    if role == 'COMPANY_ADMIN' and hasattr(user.profile, 'company') and user.profile.company:
        receipts = receipts.filter(invoice__branch__company=user.profile.company)
        branches = Branch.objects.filter(company=user.profile.company, is_deleted=False)
    elif role == 'BRANCH_ADMIN' and hasattr(user, 'managed_branch') and user.managed_branch:
        receipts = receipts.filter(invoice__branch=user.managed_branch)

    branch_id = request.GET.get('branch_id') or request.GET.get('branch')
    if branch_id:
        receipts = receipts.filter(invoice__branch_id=branch_id)

    # Date filter
    if from_date:
        try:
            parsed_from = datetime.strptime(from_date, '%Y-%m-%d').date()
            receipts = receipts.filter(created_at__date__gte=parsed_from)
        except ValueError:
            receipts = receipts.filter(created_at__date__gte=from_date)

    if to_date:
        try:
            parsed_to = datetime.strptime(to_date, '%Y-%m-%d').date()
            receipts = receipts.filter(created_at__date__lte=parsed_to)
        except ValueError:
            receipts = receipts.filter(created_at__date__lte=to_date)

    search = request.GET.get('search', '').strip()
    if search:
        receipts = receipts.filter(
            Q(receipt_number__icontains=search) |
            Q(invoice__invoice_number__icontains=search) |
            Q(invoice__customer__name__icontains=search) |
            Q(invoice__customer__phone__icontains=search) |
            Q(invoice__vehicle__vehicle_number__icontains=search)
        )

    # Summary by payment mode
    summary_grouped = receipts.values('payment_mode').annotate(total_amount=Sum('amount')).order_by('-total_amount')
    PAYMENT_LABELS = dict(Receipt.PAYMENT_CHOICES)
    mode_totals = {item['payment_mode']: item['total_amount'] or Decimal('0.00') for item in summary_grouped}

    total_collected = sum(mode_totals.values(), Decimal('0.00'))
    total_cash = mode_totals.get('cash', Decimal('0.00'))
    total_card = mode_totals.get('card', Decimal('0.00'))
    total_digital = mode_totals.get('digital_payments', Decimal('0.00'))
    total_cheque = mode_totals.get('cheque', Decimal('0.00'))
    total_online = mode_totals.get('online', Decimal('0.00'))

    summary = []
    seen_modes = set()
    for item in summary_grouped:
        mode = item['payment_mode']
        amt = item['total_amount'] or Decimal('0.00')
        seen_modes.add(mode)
        summary.append({
            'payment_mode': mode,
            'payment_mode_display': PAYMENT_LABELS.get(mode, mode.replace('_', ' ').title()),
            'total_amount': amt,
        })
    for mode, label in Receipt.PAYMENT_CHOICES:
        if mode not in seen_modes:
            summary.append({
                'payment_mode': mode,
                'payment_mode_display': label,
                'total_amount': Decimal('0.00'),
            })

    # Optional table filter by payment_mode
    payment_mode = request.GET.get('payment_mode', '').strip()
    if payment_mode:
        receipts = receipts.filter(payment_mode=payment_mode)

    table_total = receipts.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

    context = {
        'receipts': receipts,
        'summary': summary,
        'total_collected': total_collected,
        'total_cash': total_cash,
        'total_card': total_card,
        'total_digital': total_digital,
        'total_cheque': total_cheque,
        'total_online': total_online,
        'table_total': table_total,
        'from_date': from_date,
        'to_date': to_date,
        'branch_id': branch_id,
        'branches': branches,
        'search': search,
        'payment_mode': payment_mode,
        'title': 'Collection Report',
    }
    return render(request, 'reports/collection_report.html', context)


@login_required
def tax_report(request):
    user = request.user
    role = user.profile.role.name if hasattr(user, 'profile') and user.profile.role else None

    from tax_management.models import Tax, CompanyTax
    from master.models import PurchaseInvoice, Country

    today = timezone.localdate() if hasattr(timezone, 'localdate') else timezone.now().date()
    first_of_month = today.replace(day=1)

    from_date_param = request.GET.get('from_date')
    to_date_param = request.GET.get('to_date')

    if from_date_param is None and to_date_param is None:
        from_date = first_of_month.strftime('%Y-%m-%d')
        to_date = today.strftime('%Y-%m-%d')
    else:
        from_date = (from_date_param or '').strip()
        to_date = (to_date_param or '').strip()

    branch_id = (request.GET.get('branch_id') or request.GET.get('branch') or '').strip()
    tax_filter = request.GET.get('tax_filter', 'all').strip()
    tax_mode = request.GET.get('tax_mode', 'intrastate').strip()
    search = request.GET.get('search', '').strip()
    active_tab = request.GET.get('tab', 'sales').strip()

    company = None
    branches = None
    if role == 'COMPANY_ADMIN' and hasattr(user.profile, 'company') and user.profile.company:
        company = user.profile.company
        branches = Branch.objects.filter(company=company, is_deleted=False)
    elif role == 'BRANCH_ADMIN' and hasattr(user, 'managed_branch') and user.managed_branch:
        company = user.managed_branch.company
    else:
        branches = Branch.objects.filter(is_deleted=False)

    # Resolve Country based on company or user
    country = None
    if company and company.country:
        country = company.country
    elif hasattr(user, 'profile') and hasattr(user.profile, 'country') and user.profile.country:
        country = user.profile.country
    else:
        country = Country.objects.filter(name__iexact='India').first()

    country_name = country.name if country else 'India'
    is_india = (country_name.strip().lower() == 'india')

    # Query taxes for country from Settings -> Taxes
    country_taxes = []
    if country:
        country_taxes = Tax.objects.filter(country=country, is_deleted=False).order_by('name')
    elif is_india:
        india_obj = Country.objects.filter(name__iexact='India').first()
        if india_obj:
            country_taxes = Tax.objects.filter(country=india_obj, is_deleted=False).order_by('name')

    # Detect CGST, SGST, IGST rates if India
    cgst_rate = Decimal('9.00')
    sgst_rate = Decimal('9.00')
    igst_rate = Decimal('18.00')
    single_tax_rate = Decimal('0.00')
    single_tax_name = 'Tax'

    for t in country_taxes:
        tname = t.name.strip().upper()
        if 'CGST' in tname:
            cgst_rate = t.percent
        elif 'SGST' in tname:
            sgst_rate = t.percent
        elif 'IGST' in tname:
            igst_rate = t.percent
        else:
            single_tax_rate = t.percent
            single_tax_name = t.name

    # 1. Sales Invoices (Output Tax)
    invoices = Invoice.objects.filter(is_deleted=False).select_related(
        'customer', 'vehicle', 'vehicle__vehicle_type_model', 'branch'
    ).order_by('-date', '-auto_id')

    if role == 'COMPANY_ADMIN' and company:
        invoices = invoices.filter(branch__company=company)
    elif role == 'BRANCH_ADMIN' and hasattr(user, 'managed_branch') and user.managed_branch:
        invoices = invoices.filter(branch=user.managed_branch)

    if branch_id:
        invoices = invoices.filter(branch_id=branch_id)

    if from_date:
        invoices = invoices.filter(date__gte=from_date)
    if to_date:
        invoices = invoices.filter(date__lte=to_date)

    if search:
        invoices = invoices.filter(
            Q(invoice_number__icontains=search) |
            Q(customer__name__icontains=search) |
            Q(customer__phone__icontains=search) |
            Q(vehicle__vehicle_number__icontains=search)
        )

    # Aggregate before tax filter for complete KPI summary
    sales_all_agg = invoices.aggregate(
        total_tax=Sum('tax_amount'),
        total_subtotal=Sum('subtotal'),
        total_discount=Sum('discount'),
        total_gross=Sum('total'),
        total_collected=Sum('amount_collected'),
    )
    total_sales_tax = sales_all_agg['total_tax'] or Decimal('0.00')
    total_sales_subtotal = sales_all_agg['total_subtotal'] or Decimal('0.00')
    total_sales_discount = sales_all_agg['total_discount'] or Decimal('0.00')
    total_taxable_sales = max(Decimal('0.00'), total_sales_subtotal - total_sales_discount)
    total_gross_sales = sales_all_agg['total_gross'] or Decimal('0.00')
    total_invoices_count = invoices.count()
    taxed_invoices_count = invoices.filter(tax_amount__gt=0).count()
    zero_tax_invoices_count = total_invoices_count - taxed_invoices_count

    # Calculate overall CGST, SGST, IGST totals
    if is_india:
        if tax_mode == 'interstate':
            total_cgst = Decimal('0.00')
            total_sgst = Decimal('0.00')
            total_igst = total_sales_tax
        else:
            total_cgst = (total_sales_tax / Decimal('2.0')).quantize(Decimal('0.01'))
            total_sgst = total_sales_tax - total_cgst
            total_igst = Decimal('0.00')
    else:
        total_cgst = Decimal('0.00')
        total_sgst = Decimal('0.00')
        total_igst = Decimal('0.00')

    # Apply tax filter to list
    if tax_filter == 'taxed':
        invoices = invoices.filter(tax_amount__gt=0)
    elif tax_filter == 'zero':
        invoices = invoices.filter(tax_amount=0)

    # Evaluate invoice list and separate tax amounts per row
    table_sales_taxable = Decimal('0.00')
    table_sales_tax = Decimal('0.00')
    table_sales_total = Decimal('0.00')
    table_cgst = Decimal('0.00')
    table_sgst = Decimal('0.00')
    table_igst = Decimal('0.00')

    invoices_list = list(invoices)
    for inv in invoices_list:
        taxable = max(Decimal('0.00'), (inv.subtotal or Decimal('0.00')) - (inv.discount or Decimal('0.00')))
        tax_amt = inv.tax_amount or Decimal('0.00')
        inv.taxable_amount = taxable

        if is_india:
            if tax_mode == 'interstate':
                c = Decimal('0.00')
                s = Decimal('0.00')
                i = tax_amt
            else:
                c = (tax_amt / Decimal('2.0')).quantize(Decimal('0.01'))
                s = tax_amt - c
                i = Decimal('0.00')
            inv.cgst_amount = c
            inv.sgst_amount = s
            inv.igst_amount = i
            table_cgst += c
            table_sgst += s
            table_igst += i
        else:
            inv.cgst_amount = Decimal('0.00')
            inv.sgst_amount = Decimal('0.00')
            inv.igst_amount = Decimal('0.00')

        table_sales_taxable += taxable
        table_sales_tax += tax_amt
        table_sales_total += (inv.total or Decimal('0.00'))

    # 2. Purchase Invoices (Input Tax)
    purchases = PurchaseInvoice.objects.filter(is_deleted=False).select_related(
        'supplier', 'branch'
    ).order_by('-invoice_date')

    if role == 'COMPANY_ADMIN' and company:
        purchases = purchases.filter(company=company)
    elif role == 'BRANCH_ADMIN' and hasattr(user, 'managed_branch') and user.managed_branch:
        purchases = purchases.filter(branch=user.managed_branch)

    if branch_id:
        purchases = purchases.filter(branch_id=branch_id)

    if from_date:
        purchases = purchases.filter(invoice_date__gte=from_date)
    if to_date:
        purchases = purchases.filter(invoice_date__lte=to_date)

    if search:
        purchases = purchases.filter(
            Q(purchase_inv_number__icontains=search) |
            Q(supplier__name__icontains=search)
        )

    purchase_agg = purchases.aggregate(
        total_tax=Sum('tax_total'),
        total_subtotal=Sum('subtotal'),
        total_grand=Sum('grand_total'),
    )
    total_purchase_tax = purchase_agg['total_tax'] or Decimal('0.00')
    total_taxable_purchases = purchase_agg['total_subtotal'] or Decimal('0.00')
    total_purchase_grand = purchase_agg['total_grand'] or Decimal('0.00')
    total_purchases_count = purchases.count()

    total_purchase_cgst = Decimal('0.00')
    total_purchase_sgst = Decimal('0.00')
    total_purchase_igst = Decimal('0.00')

    purchases_list = list(purchases)
    for p in purchases_list:
        ptax = p.tax_total or Decimal('0.00')
        if is_india:
            if tax_mode == 'interstate':
                pc = Decimal('0.00')
                ps = Decimal('0.00')
                pi = ptax
            else:
                pc = (ptax / Decimal('2.0')).quantize(Decimal('0.01'))
                ps = ptax - pc
                pi = Decimal('0.00')
            p.cgst_amount = pc
            p.sgst_amount = ps
            p.igst_amount = pi
            total_purchase_cgst += pc
            total_purchase_sgst += ps
            total_purchase_igst += pi
        else:
            p.cgst_amount = Decimal('0.00')
            p.sgst_amount = Decimal('0.00')
            p.igst_amount = Decimal('0.00')

    # Net Tax Position: Output Tax - Input Tax
    net_tax_payable = total_sales_tax - total_purchase_tax
    net_cgst = total_cgst - total_purchase_cgst
    net_sgst = total_sgst - total_purchase_sgst
    net_igst = total_igst - total_purchase_igst

    # Configured Company Taxes from Settings -> Taxes
    company_taxes = []
    if company:
        company_taxes = CompanyTax.objects.filter(
            company=company, is_enabled=True, is_deleted=False
        ).select_related('tax').order_by('tax__name')

    currency_symbol = country.currency_symbol if country and country.currency_symbol else '₹'

    context = {
        'invoices': invoices_list,
        'purchases': purchases_list,
        'country': country,
        'country_name': country_name,
        'is_india': is_india,
        'cgst_rate': cgst_rate,
        'sgst_rate': sgst_rate,
        'igst_rate': igst_rate,
        'single_tax_rate': single_tax_rate,
        'single_tax_name': single_tax_name,
        'country_taxes': country_taxes,
        'company_taxes': company_taxes,
        'currency_symbol': currency_symbol,
        'total_sales_tax': total_sales_tax,
        'total_taxable_sales': total_taxable_sales,
        'total_gross_sales': total_gross_sales,
        'total_invoices_count': total_invoices_count,
        'taxed_invoices_count': taxed_invoices_count,
        'zero_tax_invoices_count': zero_tax_invoices_count,
        'total_cgst': total_cgst,
        'total_sgst': total_sgst,
        'total_igst': total_igst,
        'table_sales_tax': table_sales_tax,
        'table_sales_taxable': table_sales_taxable,
        'table_sales_total': table_sales_total,
        'table_cgst': table_cgst,
        'table_sgst': table_sgst,
        'table_igst': table_igst,
        'total_purchase_tax': total_purchase_tax,
        'total_taxable_purchases': total_taxable_purchases,
        'total_purchase_grand': total_purchase_grand,
        'total_purchases_count': total_purchases_count,
        'total_purchase_cgst': total_purchase_cgst,
        'total_purchase_sgst': total_purchase_sgst,
        'total_purchase_igst': total_purchase_igst,
        'net_tax_payable': net_tax_payable,
        'net_cgst': net_cgst,
        'net_sgst': net_sgst,
        'net_igst': net_igst,
        'from_date': from_date,
        'to_date': to_date,
        'branch_id': branch_id,
        'branches': branches,
        'tax_filter': tax_filter,
        'tax_mode': tax_mode,
        'search': search,
        'active_tab': active_tab,
        'title': 'Tax Report',
    }
    return render(request, 'reports/tax_report.html', context)


def _build_outstanding_report_data(request):
    user = request.user
    role = user.profile.role.name if hasattr(user, 'profile') and user.profile.role else None

    today = timezone.localdate() if hasattr(timezone, 'localdate') else timezone.now().date()

    company = None
    branches = None
    if role == 'COMPANY_ADMIN' and hasattr(user.profile, 'company') and user.profile.company:
        company = user.profile.company
        branches = Branch.objects.filter(company=company, is_deleted=False)
    elif role == 'BRANCH_ADMIN' and hasattr(user, 'managed_branch') and user.managed_branch:
        company = user.managed_branch.company
    else:
        branches = Branch.objects.filter(is_deleted=False)

    # Invoices where amount_collected < total (customer has unpaid balance)
    invoices = Invoice.objects.filter(
        is_deleted=False,
        customer__is_deleted=False,
        amount_collected__lt=F('total')
    ).select_related(
        'customer', 'branch'
    ).order_by('-date', '-auto_id')

    # Scope by role
    if role == 'COMPANY_ADMIN' and company:
        invoices = invoices.filter(branch__company=company)
    elif role == 'BRANCH_ADMIN' and hasattr(user, 'managed_branch') and user.managed_branch:
        invoices = invoices.filter(branch=user.managed_branch)

    # Filters
    branch_id = (request.GET.get('branch_id') or request.GET.get('branch') or '').strip()
    if branch_id:
        invoices = invoices.filter(branch_id=branch_id)

    from_date = (request.GET.get('from_date') or '').strip()
    to_date = (request.GET.get('to_date') or '').strip()
    if from_date:
        invoices = invoices.filter(date__gte=from_date)
    if to_date:
        invoices = invoices.filter(date__lte=to_date)

    search = (request.GET.get('search') or '').strip()
    if search:
        invoices = invoices.filter(
            Q(customer__name__icontains=search) |
            Q(customer__phone__icontains=search) |
            Q(invoice_number__icontains=search) |
            Q(vehicle__vehicle_number__icontains=search)
        )

    aging_filter = (request.GET.get('aging') or 'all').strip()

    # Aggregate by customer for summary outstanding report
    from collections import defaultdict
    customer_summary = defaultdict(lambda: {
        'customer': None,
        'customer_id': '',
        'customer_name': '',
        'customer_phone': '',
        'total_outstanding': Decimal('0.00'),
        'total_invoiced': Decimal('0.00'),
        'total_paid': Decimal('0.00'),
        'invoices_count': 0,
        'max_days_passed': 0,
    })

    total_invoices_count = 0
    total_days_passed = 0

    for inv in invoices:
        if not inv.customer:
            continue
        cid = str(inv.customer.id)
        inv_amt = inv.total or Decimal('0.00')
        paid_amt = inv.amount_collected or Decimal('0.00')
        balance = inv_amt - paid_amt

        # Days passed from invoice date to today
        if inv.date:
            days_passed = max(0, (today - inv.date).days)
        else:
            days_passed = 0

        # Apply aging filter
        if aging_filter == '0_30' and not (0 <= days_passed <= 30):
            continue
        elif aging_filter == '31_60' and not (31 <= days_passed <= 60):
            continue
        elif aging_filter == '61_90' and not (61 <= days_passed <= 90):
            continue
        elif aging_filter == '90_plus' and not (days_passed > 90):
            continue

        c = customer_summary[cid]
        c['customer'] = inv.customer
        c['customer_id'] = cid
        c['customer_name'] = inv.customer.name
        c['customer_phone'] = inv.customer.phone or ''
        c['total_outstanding'] += balance
        c['total_invoiced'] += inv_amt
        c['total_paid'] += paid_amt
        c['invoices_count'] += 1
        if days_passed > c['max_days_passed']:
            c['max_days_passed'] = days_passed

        total_days_passed += days_passed
        total_invoices_count += 1

    customer_list = [item for item in customer_summary.values() if item['total_outstanding'] > 0]
    customer_list.sort(key=lambda x: x['total_outstanding'], reverse=True)

    total_balance_amount = Decimal('0.00')
    total_inv_amount = Decimal('0.00')
    total_paid_amount = Decimal('0.00')

    for idx, item in enumerate(customer_list, start=1):
        item['sl_no'] = idx
        total_balance_amount += item['total_outstanding']
        total_inv_amount += item['total_invoiced']
        total_paid_amount += item['total_paid']

    avg_days_passed = round(total_days_passed / total_invoices_count) if total_invoices_count > 0 else 0

    currency_symbol = '₹'
    if company and company.country and company.country.currency_symbol:
        currency_symbol = company.country.currency_symbol

    from_date_display = ''
    to_date_display = ''
    if from_date:
        try:
            from datetime import datetime
            from_date_display = datetime.strptime(from_date, '%Y-%m-%d').strftime('%d %b %Y')
        except Exception:
            from_date_display = from_date
    if to_date:
        try:
            from datetime import datetime
            to_date_display = datetime.strptime(to_date, '%Y-%m-%d').strftime('%d %b %Y')
        except Exception:
            to_date_display = to_date

    return {
        'company': company,
        'customer_list': customer_list,
        'invoices': customer_list,
        'total_customers_count': len(customer_list),
        'total_inv_amount': total_inv_amount,
        'total_paid_amount': total_paid_amount,
        'total_balance_amount': total_balance_amount,
        'total_count': total_invoices_count,
        'avg_days_passed': avg_days_passed,
        'currency_symbol': currency_symbol,
        'from_date': from_date,
        'to_date': to_date,
        'from_date_display': from_date_display,
        'to_date_display': to_date_display,
        'report_date': today.strftime('%d %b %Y'),
        'branch_id': branch_id,
        'branches': branches,
        'aging': aging_filter,
        'search': search,
        'title': 'Outstanding Report',
    }


@login_required
def outstanding_report(request):
    if request.GET.get('pdf') == '1':
        return outstanding_report_pdf(request)
    context = _build_outstanding_report_data(request)
    return render(request, 'reports/outstanding_report.html', context)


@login_required
def outstanding_report_pdf(request):
    import sys, os
    if sys.platform == 'darwin':
        os.environ['DYLD_FALLBACK_LIBRARY_PATH'] = '/opt/homebrew/lib:' + os.environ.get('DYLD_FALLBACK_LIBRARY_PATH', '')
    from weasyprint import HTML

    context = _build_outstanding_report_data(request)
    html_string = render_to_string('reports/outstanding_report_pdf.html', context)
    base_url = request.build_absolute_uri('/')
    html = HTML(string=html_string, base_url=base_url)
    pdf = html.write_pdf()

    clean_date = context['report_date'].replace(' ', '_')
    filename = f"Outstanding_Report_{clean_date}.pdf"
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{filename}"'
    return response


def _build_daily_summary_data(request):
    user = request.user
    role = user.profile.role.name if hasattr(user, 'profile') and user.profile.role else None

    from decimal import Decimal
    from django.utils import timezone
    from datetime import datetime
    from django.db.models import Sum, Count, Q
    from finance_management.models import Invoice, InvoiceItem, Receipt
    from master.models import ExpenseEntry, PurchaseInvoice, Supplier
    from client_management.models import Branch, Client

    today = timezone.localdate() if hasattr(timezone, 'localdate') else timezone.now().date()
    today_str = today.strftime('%Y-%m-%d')

    from_date_raw = (request.GET.get('from_date') or request.GET.get('fromdate') or '').strip()
    to_date_raw = (request.GET.get('to_date') or request.GET.get('todate') or '').strip()

    from_date = from_date_raw if from_date_raw else today_str
    to_date = to_date_raw if to_date_raw else today_str

    branch_id = (request.GET.get('branch_id') or request.GET.get('branch') or '').strip()

    company = getattr(user.profile, 'company', None) if hasattr(user, 'profile') else None
    managed_branch = getattr(user, 'managed_branch', None)
    if not company and managed_branch:
        company = managed_branch.company

    if role == 'SUPER_ADMIN' or getattr(user, 'is_superuser', False):
        branches = Branch.objects.filter(is_deleted=False).order_by('name')
        if branch_id:
            sel_b = Branch.objects.filter(id=branch_id, is_deleted=False).first()
            if sel_b:
                company = sel_b.company
        if not company:
            company = Client.objects.filter(is_deleted=False).first()
    elif role == 'COMPANY_ADMIN' and company:
        branches = Branch.objects.filter(company=company, is_deleted=False).order_by('name')
    elif role == 'BRANCH_ADMIN' and managed_branch:
        branches = Branch.objects.filter(id=managed_branch.id, is_deleted=False)
        branch_id = str(managed_branch.id)
    else:
        branches = Branch.objects.filter(is_deleted=False).order_by('name')
        if not company:
            company = Client.objects.filter(is_deleted=False).first()

    currency_symbol = '₹'
    if company and company.country and company.country.currency_symbol:
        currency_symbol = company.country.currency_symbol

    # Base QuerySets with scope
    inv_qs = Invoice.objects.filter(is_deleted=False, date__gte=from_date, date__lte=to_date)
    exp_qs = ExpenseEntry.objects.filter(is_deleted=False, expense_date__gte=from_date, expense_date__lte=to_date)
    rcpt_qs = Receipt.objects.filter(is_deleted=False, invoice__is_deleted=False, created_at__date__gte=from_date, created_at__date__lte=to_date)
    purch_qs = PurchaseInvoice.objects.filter(is_deleted=False, invoice_date__gte=from_date, invoice_date__lte=to_date)

    if branch_id:
        inv_qs = inv_qs.filter(branch_id=branch_id)
        exp_qs = exp_qs.filter(branch_id=branch_id)
        rcpt_qs = rcpt_qs.filter(invoice__branch_id=branch_id)
        purch_qs = purch_qs.filter(branch_id=branch_id)
    elif role == 'COMPANY_ADMIN' and company:
        inv_qs = inv_qs.filter(branch__company=company)
        exp_qs = exp_qs.filter(branch__company=company)
        rcpt_qs = rcpt_qs.filter(invoice__branch__company=company)
        purch_qs = purch_qs.filter(branch__company=company)
    elif role == 'BRANCH_ADMIN' and managed_branch:
        inv_qs = inv_qs.filter(branch=managed_branch)
        exp_qs = exp_qs.filter(branch=managed_branch)
        rcpt_qs = rcpt_qs.filter(invoice__branch=managed_branch)
        purch_qs = purch_qs.filter(branch=managed_branch)

    # 1. Sales Table (Services) & Stock Items Table
    inv_list = inv_qs.prefetch_related('items', 'items__stock_item').order_by('-date', '-auto_id')
    services_map = {}
    stock_items_map = {}

    for inv in inv_list:
        ratio = (inv.amount_collected / inv.total) if (inv.total and inv.total > 0) else Decimal('0.00')
        if ratio > Decimal('1.00'):
            ratio = Decimal('1.00')
        items = list(inv.items.filter(is_deleted=False))
        if not items:
            s_name = 'General / Direct Sale'
            if s_name not in services_map:
                services_map[s_name] = {'service': s_name, 'totalno': Decimal('0'), 'amount': Decimal('0'), 'received': Decimal('0'), 'balance': Decimal('0')}
            services_map[s_name]['totalno'] += Decimal('1')
            services_map[s_name]['amount'] += inv.total
            services_map[s_name]['received'] += inv.amount_collected
            services_map[s_name]['balance'] += (inv.total - inv.amount_collected)
        else:
            raw_amts = [it.net_taxable_amount if (it.net_taxable_amount is not None and it.net_taxable_amount > 0) else (it.rate * it.qty - it.discount) for it in items]
            sum_raw = sum(raw_amts)
            for it, r_amt in zip(items, raw_amts):
                if sum_raw > 0:
                    it_amt = (r_amt / sum_raw) * inv.total
                else:
                    it_amt = inv.total / Decimal(str(len(items)))
                it_rec = it_amt * ratio
                it_bal = it_amt - it_rec

                is_stock = bool(it.stock_item_id or it.stock_item)
                if is_stock:
                    item_name = (it.service_name or (it.stock_item.item_name if it.stock_item else 'Stock Item')).strip()
                    if item_name not in stock_items_map:
                        stock_items_map[item_name] = {'item': item_name, 'totalno': Decimal('0'), 'amount': Decimal('0'), 'received': Decimal('0'), 'balance': Decimal('0')}
                    stock_items_map[item_name]['totalno'] += (it.qty or Decimal('1'))
                    stock_items_map[item_name]['amount'] += it_amt
                    stock_items_map[item_name]['received'] += it_rec
                    stock_items_map[item_name]['balance'] += it_bal
                else:
                    s_name = (it.service_name or 'General Service').strip()
                    if s_name not in services_map:
                        services_map[s_name] = {'service': s_name, 'totalno': Decimal('0'), 'amount': Decimal('0'), 'received': Decimal('0'), 'balance': Decimal('0')}
                    services_map[s_name]['totalno'] += (it.qty or Decimal('1'))
                    services_map[s_name]['amount'] += it_amt
                    services_map[s_name]['received'] += it_rec
                    services_map[s_name]['balance'] += it_bal

    sales_rows = sorted(services_map.values(), key=lambda x: x['amount'], reverse=True)
    for idx, row in enumerate(sales_rows, start=1):
        row['slno'] = idx

    sales_totals = {
        'totalno': sum((r['totalno'] for r in sales_rows), Decimal('0')),
        'amount': sum((r['amount'] for r in sales_rows), Decimal('0')),
        'received': sum((r['received'] for r in sales_rows), Decimal('0')),
        'balance': sum((r['balance'] for r in sales_rows), Decimal('0')),
    }

    stock_rows = sorted(stock_items_map.values(), key=lambda x: x['amount'], reverse=True)
    for idx, row in enumerate(stock_rows, start=1):
        row['slno'] = idx

    stock_totals = {
        'totalno': sum((r['totalno'] for r in stock_rows), Decimal('0')),
        'amount': sum((r['amount'] for r in stock_rows), Decimal('0')),
        'received': sum((r['received'] for r in stock_rows), Decimal('0')),
        'balance': sum((r['balance'] for r in stock_rows), Decimal('0')),
    }

    total_sales_received = sales_totals['received'] + stock_totals['received']
    total_sales_amount = sales_totals['amount'] + stock_totals['amount']

    # 2. Expense Table (slno, expensehead, amount, paid, balance)
    exp_filtered = exp_qs.exclude(expense__expense_head__name__iexact='Purchase')
    exp_grouped = exp_filtered.values('expense__expense_head__name').annotate(
        amount=Sum('amount'),
        paid=Sum('paid_amount')
    ).order_by('-amount')

    expense_rows = []
    for idx, e in enumerate(exp_grouped, start=1):
        amt = e['amount'] or Decimal('0.00')
        pd = e['paid'] or Decimal('0.00')
        bal = amt - pd
        expense_rows.append({
            'slno': idx,
            'expensehead': e['expense__expense_head__name'] or 'General Expense',
            'amount': amt,
            'paid': pd,
            'balance': bal,
        })

    expense_totals = {
        'amount': sum((r['amount'] for r in expense_rows), Decimal('0.00')),
        'paid': sum((r['paid'] for r in expense_rows), Decimal('0.00')),
        'balance': sum((r['balance'] for r in expense_rows), Decimal('0.00')),
    }

    # 3. Collection Table (previous outstanding collection: slno, customername, amount)
    prev_coll_qs = rcpt_qs.filter(invoice__date__lt=from_date).values(
        'invoice__customer__id',
        'invoice__customer__name',
        'invoice__customer__phone'
    ).annotate(total_amount=Sum('amount')).order_by('-total_amount')

    collection_rows = []
    for idx, c in enumerate(prev_coll_qs, start=1):
        name = c['invoice__customer__name'] or 'Unknown Customer'
        phone = c['invoice__customer__phone'] or ''
        amt = c['total_amount'] or Decimal('0.00')
        collection_rows.append({
            'slno': idx,
            'customername': name,
            'customerphone': phone,
            'amount': amt,
        })

    collection_totals = {
        'amount': sum((r['amount'] for r in collection_rows), Decimal('0.00')),
    }

    # 4. Purchase Table (slno, supplier, invo.no, amount, paid, balance)
    purch_list = purch_qs.select_related('supplier').order_by('-invoice_date', '-date_added')
    purchase_rows = []
    for idx, p in enumerate(purch_list, start=1):
        purchase_rows.append({
            'slno': idx,
            'supplier': p.supplier.name if p.supplier else 'Unknown Supplier',
            'invo_no': p.purchase_inv_number or '-',
            'amount': p.grand_total or Decimal('0.00'),
            'paid': p.amount_paid or Decimal('0.00'),
            'balance': p.balance_to_pay or Decimal('0.00'),
        })

    purchase_totals = {
        'amount': sum((r['amount'] for r in purchase_rows), Decimal('0.00')),
        'paid': sum((r['paid'] for r in purchase_rows), Decimal('0.00')),
        'balance': sum((r['balance'] for r in purchase_rows), Decimal('0.00')),
    }

    # Cash / Payment breakdown at bottom
    # Receipts collected during this period
    cash_collected = rcpt_qs.filter(Q(payment_mode__iexact='cash')).aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
    card_collected = rcpt_qs.filter(Q(payment_mode__iexact='card')).aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
    digital_collected = rcpt_qs.filter(
        Q(payment_mode__iexact='digital_payments') |
        Q(payment_mode__iexact='online') |
        Q(payment_mode__iexact='cheque')
    ).aggregate(s=Sum('amount'))['s'] or Decimal('0.00')

    # Cash expenses & purchases paid out in cash during this period
    cash_expense_paid = exp_qs.filter(Q(payment_mode__iexact='CASH')).aggregate(s=Sum('paid_amount'))['s'] or Decimal('0.00')
    cash_purchase_paid = purch_qs.filter(Q(payment_mode__iexact='CASH')).aggregate(s=Sum('amount_paid'))['s'] or Decimal('0.00')
    total_cash_out = cash_expense_paid + cash_purchase_paid

    net_cash_in_hand = cash_collected - total_cash_out
    total_inflow = cash_collected + card_collected + digital_collected

    from_date_display = ''
    to_date_display = ''
    try:
        from_date_display = datetime.strptime(from_date, '%Y-%m-%d').strftime('%d %b %Y')
    except Exception:
        from_date_display = from_date
    try:
        to_date_display = datetime.strptime(to_date, '%Y-%m-%d').strftime('%d %b %Y')
    except Exception:
        to_date_display = to_date

    selected_branch_name = ''
    if branch_id and branches:
        for b in branches:
            if str(b.id) == str(branch_id):
                selected_branch_name = b.name
                break

    return {
        'company': company,
        'branches': branches,
        'branch_id': branch_id,
        'selected_branch_name': selected_branch_name,
        'from_date': from_date,
        'to_date': to_date,
        'from_date_display': from_date_display,
        'to_date_display': to_date_display,
        'report_date': today.strftime('%d %b %Y'),
        'currency_symbol': currency_symbol,

        'sales_rows': sales_rows,
        'sales_totals': sales_totals,

        'stock_rows': stock_rows,
        'stock_totals': stock_totals,
        'total_sales_received': total_sales_received,
        'total_sales_amount': total_sales_amount,

        'expense_rows': expense_rows,
        'expense_totals': expense_totals,

        'collection_rows': collection_rows,
        'collection_totals': collection_totals,

        'purchase_rows': purchase_rows,
        'purchase_totals': purchase_totals,

        'cash_collected': cash_collected,
        'cash_expense_paid': cash_expense_paid,
        'cash_purchase_paid': cash_purchase_paid,
        'total_cash_out': total_cash_out,
        'net_cash_in_hand': net_cash_in_hand,
        'card_collected': card_collected,
        'digital_collected': digital_collected,
        'total_inflow': total_inflow,

        'title': 'Daily Summary Report',
    }


@login_required
def daily_summary_report(request):
    if request.GET.get('pdf') == '1':
        return daily_summary_report_pdf(request)
    context = _build_daily_summary_data(request)
    return render(request, 'reports/daily_summary_report.html', context)


@login_required
def daily_summary_report_pdf(request):
    import sys, os
    if sys.platform == 'darwin':
        os.environ['DYLD_FALLBACK_LIBRARY_PATH'] = '/opt/homebrew/lib:' + os.environ.get('DYLD_FALLBACK_LIBRARY_PATH', '')
    from weasyprint import HTML

    context = _build_daily_summary_data(request)
    html_string = render_to_string('reports/daily_summary_report_pdf.html', context)
    base_url = request.build_absolute_uri('/')
    html = HTML(string=html_string, base_url=base_url)
    pdf = html.write_pdf()

    clean_date = context['report_date'].replace(' ', '_')
    filename = f"Daily_Summary_Report_{clean_date}.pdf"
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{filename}"'
    return response


@login_required
def stock_report(request):
    """
    Comprehensive Stock & Inventory Report
    ────────────────────────────────────────
    Displays stock levels, trading vs operational status, purchase vs consumption metrics,
    low stock alerts, group & sub-group filtering, and CSV export.
    """
    from client_management.models import Stock, Client
    from master.models import StockGroup, StockSubGroup, PurchaseInvoiceItem
    from finance_management.models import InvoiceItem
    from django.db.models import Sum, Q
    from django.core.paginator import Paginator
    import csv

    user = request.user
    role = None
    if hasattr(user, 'profile') and user.profile.role:
        role = user.profile.role.name

    company = None
    if role == 'COMPANY_ADMIN':
        if hasattr(user, 'profile') and user.profile.company:
            company = user.profile.company
    elif role == 'BRANCH_ADMIN':
        if hasattr(user, 'managed_branch') and user.managed_branch and user.managed_branch.company:
            company = user.managed_branch.company
        elif hasattr(user, 'profile') and user.profile.company:
            company = user.profile.company

    # Base Stock Queryset
    stocks = Stock.objects.filter(is_deleted=False).select_related(
        'group', 'sub_group', 'company', 'expense_head'
    ).order_by('item_name')

    # Company Scope
    company_id_param = request.GET.get('company_id', '').strip()
    if company:
        stocks = stocks.filter(Q(company=company) | Q(company__isnull=True))
    elif user.is_superuser and company_id_param:
        stocks = stocks.filter(company_id=company_id_param)

    # Filter Options
    groups = StockGroup.objects.filter(is_deleted=False)
    sub_groups = StockSubGroup.objects.filter(is_deleted=False)
    if company:
        groups = groups.filter(Q(company=company) | Q(company__isnull=True))
        sub_groups = sub_groups.filter(Q(company=company) | Q(company__isnull=True))
    groups = groups.order_by('name')
    sub_groups = sub_groups.order_by('name')

    companies = Client.objects.filter(is_deleted=False).order_by('company_name') if user.is_superuser else []

    # Get Filter Parameters
    search = request.GET.get('search', '').strip()
    group_id = request.GET.get('group_id', '').strip()
    sub_group_id = request.GET.get('sub_group_id', '').strip()
    item_type = request.GET.get('item_type', 'all').strip().lower()
    stock_status = request.GET.get('stock_status', 'all').strip().lower()

    if search:
        stocks = stocks.filter(
            Q(item_name__icontains=search) |
            Q(brand__icontains=search) |
            Q(barcode__icontains=search) |
            Q(hsn_code__icontains=search)
        )

    if group_id:
        stocks = stocks.filter(group_id=group_id)

    if sub_group_id:
        stocks = stocks.filter(sub_group_id=sub_group_id)

    if item_type == 'trading':
        stocks = stocks.filter(is_trading=True, is_operational=False)
    elif item_type == 'operational':
        stocks = stocks.filter(is_operational=True)

    # Pre-fetch or aggregate purchase and consumption quantities efficiently
    stock_ids = [s.id for s in stocks]

    # Purchase aggregations
    purchases_map = {}
    if stock_ids:
        p_qs = PurchaseInvoiceItem.objects.filter(stock_item_id__in=stock_ids, is_deleted=False)
        if company:
            p_qs = p_qs.filter(purchase_invoice__company=company)
        p_agg = p_qs.values('stock_item_id').annotate(
            total_qty=Sum('quantity'),
            total_val=Sum('total_including_tax')
        )
        for item in p_agg:
            purchases_map[item['stock_item_id']] = {
                'qty': float(item['total_qty'] or 0),
                'val': float(item['total_val'] or 0),
            }

    # Invoice Consumption aggregations
    consumptions_map = {}
    if stock_ids:
        c_qs = InvoiceItem.objects.filter(stock_item_id__in=stock_ids, is_deleted=False, invoice__is_deleted=False)
        if company:
            c_qs = c_qs.filter(invoice__branch__company=company)
        c_agg = c_qs.values('stock_item_id').annotate(
            total_qty=Sum('qty'),
            total_val=Sum('net_taxable_amount')
        )
        for item in c_agg:
            consumptions_map[item['stock_item_id']] = {
                'qty': float(item['total_qty'] or 0),
                'val': float(item['total_val'] or 0),
            }

    rows = []
    total_items = 0
    total_current_qty = 0
    total_purchased_qty = 0
    total_consumed_qty = 0
    low_stock_count = 0
    out_of_stock_count = 0

    for stock in stocks:
        current_qty = float(stock.quantity or 0)
        crit_level = float(stock.critical_level or 0)

        # Status check
        if current_qty <= 0:
            status_code = 'OUT_OF_STOCK'
            status_label = 'Out of Stock'
            status_badge = 'badge-danger'
        elif current_qty <= crit_level:
            status_code = 'LOW_STOCK'
            status_label = 'Low Stock'
            status_badge = 'badge-warning'
        else:
            status_code = 'IN_STOCK'
            status_label = 'In Stock'
            status_badge = 'badge-success'

        # Filter by stock_status if requested
        if stock_status == 'in_stock' and status_code != 'IN_STOCK':
            continue
        elif stock_status == 'low_stock' and status_code != 'LOW_STOCK':
            continue
        elif stock_status == 'out_of_stock' and status_code != 'OUT_OF_STOCK':
            continue

        p_info = purchases_map.get(stock.id, {'qty': 0, 'val': 0})
        c_info = consumptions_map.get(stock.id, {'qty': 0, 'val': 0})

        purchased_qty = p_info['qty']
        consumed_qty = c_info['qty']

        total_items += 1
        total_current_qty += current_qty
        total_purchased_qty += purchased_qty
        total_consumed_qty += consumed_qty

        if status_code == 'OUT_OF_STOCK':
            out_of_stock_count += 1
        elif status_code == 'LOW_STOCK':
            low_stock_count += 1

        vat = float(getattr(stock, 'vat_percent', 0) or 0)
        cgst = float(stock.cgst_percent or 0)
        sgst = float(stock.sgst_percent or 0)
        igst = float(stock.igst_percent or 0)
        tax_rate = round(vat or (cgst + sgst + igst), 2)

        unit_name = stock.get_unit_display() if hasattr(stock, 'get_unit_display') else (stock.unit or 'Piece')

        rows.append({
            'stock': stock,
            'item_name': stock.item_name,
            'brand': stock.brand or '-',
            'barcode': stock.barcode or '',
            'hsn_code': stock.hsn_code or '',
            'group_name': stock.group.name if stock.group else 'General',
            'sub_group_name': stock.sub_group.name if stock.sub_group else '-',
            'unit': unit_name,
            'is_trading': stock.is_trading,
            'is_operational': stock.is_operational,
            'critical_level': crit_level,
            'current_qty': current_qty,
            'purchased_qty': purchased_qty,
            'consumed_qty': consumed_qty,
            'tax_rate': tax_rate,
            'status_code': status_code,
            'status_label': status_label,
            'status_badge': status_badge,
            'company_name': stock.company.company_name if stock.company else 'Global',
            'client_code': stock.company.display_client_id if stock.company else 'GLOBAL',
        })

    # CSV Export
    if request.GET.get('export') == 'csv':
        from django.http import HttpResponse
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="Stock_Report.csv"'
        writer = csv.writer(response)
        writer.writerow([
            'SL No', 'Item Name', 'Brand', 'Barcode', 'HSN Code',
            'Group', 'Sub-Group', 'Unit', 'Type', 'Critical Level',
            'Purchased Qty', 'Consumed Qty', 'Current Stock', 'Status'
        ])
        for idx, r in enumerate(rows, 1):
            if r['is_trading'] and r['is_operational']:
                item_type_str = 'Trading & Operational'
            elif r['is_operational']:
                item_type_str = 'Operational'
            else:
                item_type_str = 'Trading'
            writer.writerow([
                idx, r['item_name'], r['brand'], r['barcode'], r['hsn_code'],
                r['group_name'], r['sub_group_name'], r['unit'], item_type_str,
                r['critical_level'], r['purchased_qty'], r['consumed_qty'],
                r['current_qty'], r['status_label']
            ])
        return response

    paginator = Paginator(rows, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    summary = {
        'total_items': total_items,
        'total_current_qty': round(total_current_qty, 2),
        'total_purchased_qty': round(total_purchased_qty, 2),
        'total_consumed_qty': round(total_consumed_qty, 2),
        'low_stock_count': low_stock_count,
        'out_of_stock_count': out_of_stock_count,
    }

    return render(request, 'reports/stock_report.html', {
        'page_obj': page_obj,
        'summary': summary,
        'groups': groups,
        'sub_groups': sub_groups,
        'companies': companies,
        'search': search,
        'group_id': group_id,
        'sub_group_id': sub_group_id,
        'item_type': item_type,
        'stock_status': stock_status,
        'company_id': company_id_param,
        'title': 'Stock Report',
    })


@login_required
def invoice_customisation_redirect(request):
    """Redirect to the first branch invoice customisation page."""
    role = getattr(getattr(request.user, 'profile', None), 'role', None)
    role_name = role.name if role else None

    if role_name == 'COMPANY_ADMIN':
        company = getattr(request.user.profile, 'company', None)
        first_branch = Branch.objects.filter(company=company, is_deleted=False).order_by('name').first()
        if first_branch:
            return redirect('invoice_customisation_manage', branch_id=first_branch.id)
        messages.warning(request, "No branches found for your company.")
        return redirect('dashboard')
    elif role_name == 'BRANCH_ADMIN':
        branch = getattr(request.user, 'managed_branch', None)
        if branch:
            return redirect('invoice_customisation_manage', branch_id=branch.id)
        messages.warning(request, "No managed branch found.")
        return redirect('dashboard')
    else:
        first_branch = Branch.objects.filter(is_deleted=False).order_by('name').first()
        if first_branch:
            return redirect('invoice_customisation_manage', branch_id=first_branch.id)
        return redirect('dashboard')


@login_required
def invoice_customisation_manage(request, branch_id):
    branch = get_object_or_404(Branch, id=branch_id, is_deleted=False)
    role = getattr(getattr(request.user, 'profile', None), 'role', None)
    role_name = role.name if role else None

    company_branches = []
    if role_name == 'COMPANY_ADMIN':
        company = getattr(request.user.profile, 'company', None)
        if company:
            company_branches = Branch.objects.filter(company=company, is_deleted=False).order_by('name')
    elif role_name == 'BRANCH_ADMIN':
        if getattr(request.user, 'managed_branch', None) != branch:
            messages.error(request, "Access denied.")
            return redirect('dashboard')
        company_branches = [branch]
    else:
        company_branches = Branch.objects.filter(is_deleted=False).order_by('name')

    customisation, _ = BranchInvoiceCustomisation.objects.get_or_create(
        branch=branch,
        defaults={
            'auto_id': get_auto_id(BranchInvoiceCustomisation),
            'creator': request.user,
            'non_tax_title': 'PROFORMA INVOICE',
            'show_vehicle_number': True,
            'show_vehicle_make': True,
            'show_vehicle_model': True,
            'show_vehicle_segment': True,
            'show_vehicle_type': True,
            'show_vehicle_color': True,
            'show_vehicle_fuel_type': True,
            'show_vehicle_wheel_type': True,
            'show_vehicle_emission_std': True,
            'show_vehicle_odometer': True,
            'send_invoice_via_whatsapp': False,
            'oil_change_odometer_required': True,
            'oil_change_reminder_required': True,
        }
    )

    if request.method == 'POST':
        non_tax_title = request.POST.get('non_tax_title', 'PROFORMA INVOICE').strip()
        if non_tax_title not in ['INVOICE', 'PROFORMA INVOICE']:
            non_tax_title = 'PROFORMA INVOICE'

        customisation.non_tax_title = non_tax_title
        customisation.show_vehicle_number = (request.POST.get('show_vehicle_number') == 'on')
        customisation.show_vehicle_make = (request.POST.get('show_vehicle_make') == 'on')
        customisation.show_vehicle_model = (request.POST.get('show_vehicle_model') == 'on')
        customisation.show_vehicle_segment = (request.POST.get('show_vehicle_segment') == 'on')
        customisation.show_vehicle_type = (request.POST.get('show_vehicle_type') == 'on')
        customisation.show_vehicle_color = (request.POST.get('show_vehicle_color') == 'on')
        customisation.show_vehicle_fuel_type = (request.POST.get('show_vehicle_fuel_type') == 'on')
        customisation.show_vehicle_wheel_type = (request.POST.get('show_vehicle_wheel_type') == 'on')
        customisation.show_vehicle_emission_std = (request.POST.get('show_vehicle_emission_std') == 'on')
        customisation.show_vehicle_odometer = (request.POST.get('show_vehicle_odometer') == 'on')
        customisation.send_invoice_via_whatsapp = (request.POST.get('send_invoice_via_whatsapp') == 'on')
        customisation.oil_change_odometer_required = (request.POST.get('oil_change_odometer_required') == 'on')
        customisation.oil_change_reminder_required = (request.POST.get('oil_change_reminder_required') == 'on')
        customisation.save()

        messages.success(request, f"Invoice customisation for {branch.name} saved successfully.")
        return redirect('invoice_customisation_manage', branch_id=branch.id)

    return render(request, 'invoice/invoice_customisation.html', {
        'branch': branch,
        'company_branches': company_branches,
        'customisation': customisation,
        'role_name': role_name,
        'title': f'Invoice Customisation — {branch.name}',
    })


@login_required
def credit_note_report(request):
    import csv
    from django.http import HttpResponse
    from django.shortcuts import render
    from django.db.models import Sum, Q
    from decimal import Decimal
    from datetime import datetime
    from django.utils import timezone
    from finance_management.models import CreditNote
    from client_management.models import Branch

    user = request.user
    role = user.profile.role.name if hasattr(user, 'profile') and user.profile.role else None

    today = timezone.localdate() if hasattr(timezone, 'localdate') else timezone.now().date()
    today_str = today.strftime('%Y-%m-%d')

    from_date_param = request.GET.get('from_date') or request.GET.get('fromdate')
    to_date_param = request.GET.get('to_date') or request.GET.get('todate')

    if from_date_param:
        from_date = from_date_param.strip()
    else:
        from_date = today.replace(day=1).strftime('%Y-%m-%d')

    if to_date_param:
        to_date = to_date_param.strip()
    else:
        to_date = today_str

    credit_notes = CreditNote.objects.filter(is_deleted=False).select_related(
        'invoice', 'invoice__customer', 'invoice__vehicle', 'customer', 'branch', 'creator'
    ).order_by('-date_added')

    branches = None
    if role == 'COMPANY_ADMIN' and hasattr(user.profile, 'company') and user.profile.company:
        credit_notes = credit_notes.filter(branch__company=user.profile.company)
        branches = Branch.objects.filter(company=user.profile.company, is_deleted=False)
    elif role == 'BRANCH_ADMIN' and hasattr(user, 'managed_branch') and user.managed_branch:
        credit_notes = credit_notes.filter(branch=user.managed_branch)
    elif role == 'SUPER_ADMIN':
        branches = Branch.objects.filter(is_deleted=False)

    branch_id = request.GET.get('branch_id') or request.GET.get('branch')
    if branch_id:
        credit_notes = credit_notes.filter(branch_id=branch_id)

    # Date filter
    if from_date:
        try:
            parsed_from = datetime.strptime(from_date, '%Y-%m-%d').date()
            credit_notes = credit_notes.filter(date__gte=parsed_from)
        except ValueError:
            credit_notes = credit_notes.filter(date__gte=from_date)

    if to_date:
        try:
            parsed_to = datetime.strptime(to_date, '%Y-%m-%d').date()
            credit_notes = credit_notes.filter(date__lte=parsed_to)
        except ValueError:
            credit_notes = credit_notes.filter(date__lte=to_date)

    # Search filter
    search = request.GET.get('search', '').strip()
    if search:
        credit_notes = credit_notes.filter(
            Q(credit_note_number__icontains=search) |
            Q(invoice__invoice_number__icontains=search) |
            Q(customer__name__icontains=search) |
            Q(customer__phone__icontains=search) |
            Q(invoice__vehicle__vehicle_number__icontains=search) |
            Q(reason__icontains=search)
        )

    # Reason filter
    reason = request.GET.get('reason', '').strip()
    if reason:
        credit_notes = credit_notes.filter(reason=reason)

    # CSV Export
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="Credit_Note_Report_{from_date}_to_{to_date}.csv"'
        writer = csv.writer(response)
        writer.writerow([
            'SL No', 'Credit Note No', 'Date', 'Invoice No', 'Customer Name', 'Phone',
            'Vehicle No', 'Branch', 'Reason', 'Remarks', 'Subtotal', 'Tax Amount', 'Total Amount', 'Created By'
        ])
        for idx, cn in enumerate(credit_notes, 1):
            writer.writerow([
                idx,
                cn.credit_note_number,
                cn.date.strftime('%Y-%m-%d') if cn.date else '',
                cn.invoice.invoice_number if cn.invoice else '',
                cn.customer.name if cn.customer else '',
                cn.customer.phone if cn.customer else '',
                cn.invoice.vehicle.vehicle_number if cn.invoice and cn.invoice.vehicle else '',
                cn.branch.name if cn.branch else '',
                cn.reason or '',
                cn.remarks or '',
                f"{cn.subtotal:.2f}",
                f"{cn.tax_amount:.2f}",
                f"{cn.total:.2f}",
                cn.creator.username if cn.creator else '',
            ])
        return response

    # Metrics
    total_count = credit_notes.count()
    aggregates = credit_notes.aggregate(
        total_amount=Sum('total'),
        total_subtotal=Sum('subtotal'),
        total_tax=Sum('tax_amount')
    )
    total_amount = aggregates['total_amount'] or Decimal('0.00')
    total_subtotal = aggregates['total_subtotal'] or Decimal('0.00')
    total_tax = aggregates['total_tax'] or Decimal('0.00')
    avg_amount = (total_amount / total_count) if total_count > 0 else Decimal('0.00')

    distinct_reasons = CreditNote.objects.filter(is_deleted=False).exclude(reason__isnull=True).exclude(reason='').values_list('reason', flat=True).distinct()

    context = {
        'credit_notes': credit_notes,
        'total_count': total_count,
        'total_amount': total_amount,
        'total_subtotal': total_subtotal,
        'total_tax': total_tax,
        'avg_amount': avg_amount,
        'from_date': from_date,
        'to_date': to_date,
        'branch_id': branch_id,
        'branches': branches,
        'search': search,
        'reason': reason,
        'distinct_reasons': distinct_reasons,
        'title': 'Credit Note Report',
    }
    return render(request, 'reports/credit_note_report.html', context)


@csrf_exempt
def api_credit_note_report(request):
    user = get_user_from_token(request)
    if not user:
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=401)

    role = user.profile.role.name if hasattr(user, 'profile') and user.profile.role else None

    from finance_management.models import CreditNote
    from django.db.models import Sum, Q
    from decimal import Decimal

    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    branch_id = request.GET.get('branch_id')

    credit_notes = CreditNote.objects.filter(is_deleted=False).select_related(
        'invoice', 'customer', 'branch'
    ).order_by('-date_added')

    if role == 'BRANCH_ADMIN' and hasattr(user, 'managed_branch'):
        credit_notes = credit_notes.filter(branch=user.managed_branch)
    elif role == 'COMPANY_ADMIN' and hasattr(user.profile, 'company'):
        credit_notes = credit_notes.filter(branch__company=user.profile.company)

    if branch_id:
        credit_notes = credit_notes.filter(branch_id=branch_id)
    if from_date:
        credit_notes = credit_notes.filter(date__gte=from_date)
    if to_date:
        credit_notes = credit_notes.filter(date__lte=to_date)

    items = []
    for cn in credit_notes:
        items.append({
            'id': str(cn.id),
            'credit_note_number': cn.credit_note_number,
            'invoice_number': cn.invoice.invoice_number if cn.invoice else '',
            'customer_name': cn.customer.name if cn.customer else '',
            'customer_phone': cn.customer.phone if cn.customer else '',
            'date': str(cn.date),
            'total': str(cn.total),
            'reason': cn.reason or '',
            'remarks': cn.remarks or '',
            'branch_name': cn.branch.name if cn.branch else '',
        })

    total_amount = credit_notes.aggregate(t=Sum('total'))['t'] or Decimal('0.00')

    return JsonResponse({
        'success': True,
        'credit_notes': items,
        'total_count': len(items),
        'total_amount': str(total_amount),
    })


