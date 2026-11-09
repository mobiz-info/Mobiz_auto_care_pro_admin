import os
import sys
import openpyxl
from decimal import Decimal
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wash_pilot.settings')
import django
django.setup()

from django.utils import timezone
from django.db import transaction
from django.db.models import Max
from client_management.models import Client, Stock
from master.models import StockGroup, StockSubGroup, ExpenseHead
from django.contrib.auth.models import User
from core.functions import get_auto_id

EXCEL_FILE = '/Users/muhammedanshid/Desktop/Mobiz Car Wash/Mobiz Carwash Admin/OPENING STOCK NOV 2026.xlsx'
COMPANY_ID = 'b0576eb1-80e2-4945-9bb8-0636d4b65606'
OPENING_DATE = datetime(2026, 11, 1, 0, 0, 0, tzinfo=timezone.utc)

def run_import():
    company = Client.objects.filter(id=COMPANY_ID, is_deleted=False).first()
    if not company:
        print(f"Error: Company {COMPANY_ID} not found.")
        return

    creator = User.objects.filter(username='oalbab').first()
    if not creator:
        creator = User.objects.filter(is_superuser=True).first()

    print(f"Target Company: {company.company_name} (ID: {company.id})")
    print(f"Creator User: {creator.username}")
    print(f"Opening Date: {OPENING_DATE.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    expense_head = ExpenseHead.objects.filter(
        company=company, name__iexact='Purchase', is_deleted=False
    ).first()
    if not expense_head:
        expense_head = ExpenseHead.objects.filter(
            company__isnull=True, name__iexact='Purchase', is_deleted=False
        ).first()

    wb = openpyxl.load_workbook(EXCEL_FILE, data_only=True)
    ws = wb.active

    # Parse rows
    parsed_items = []
    for r in range(2, ws.max_row + 1):
        name = ws.cell(row=r, column=5).value
        if not name or str(name).strip() == '':
            continue

        code = str(ws.cell(row=r, column=2).value or '').strip()
        cat = str(ws.cell(row=r, column=3).value or '').strip()
        subcat = str(ws.cell(row=r, column=4).value or '').strip()
        item_name = str(name).strip()
        
        # Stock count
        raw_qty = ws.cell(row=r, column=6).value
        try:
            qty = Decimal(str(raw_qty or 0).strip())
        except Exception:
            qty = Decimal('0.00')

        # Unit
        raw_unit = str(ws.cell(row=r, column=7).value or 'Piece').strip().lower()
        if 'ltr' in raw_unit:
            unit_val = 'Litre'
        elif 'drum' in raw_unit:
            unit_val = 'Barrel'
        elif 'box' in raw_unit:
            unit_val = 'Box'
        elif 'can' in raw_unit:
            unit_val = 'Can'
        elif 'bottle' in raw_unit:
            unit_val = 'Bottle'
        else:
            unit_val = 'Piece'

        # Purchase rate
        raw_purchase = ws.cell(row=r, column=8).value
        try:
            purchase_rate = Decimal(str(raw_purchase or 0).strip()) if raw_purchase is not None else Decimal('0.00')
        except Exception:
            purchase_rate = Decimal('0.00')

        # Selling rate
        raw_selling = ws.cell(row=r, column=9).value
        try:
            selling_rate = Decimal(str(raw_selling or 0).strip()) if raw_selling is not None else Decimal('0.00')
        except Exception:
            selling_rate = Decimal('0.00')

        # Flags
        raw_trade = str(ws.cell(row=r, column=10).value or '').strip().upper()
        raw_oper = str(ws.cell(row=r, column=11).value or '').strip().upper()
        is_trading = (raw_trade == 'YES')
        is_operational = (raw_oper == 'YES')

        parsed_items.append({
            'row': r,
            'code': code,
            'cat': cat,
            'subcat': subcat,
            'name': item_name,
            'qty': qty,
            'unit': unit_val,
            'purchase_rate': purchase_rate,
            'selling_rate': selling_rate,
            'is_trading': is_trading,
            'is_operational': is_operational,
        })

    print(f"Total valid rows parsed: {len(parsed_items)}")

    # Groups and Subgroups cache
    group_map = {}
    subgroup_map = {}

    with transaction.atomic():
        # Pre-create/fetch groups
        for item in parsed_items:
            cat_name = item['cat']
            subcat_name = item['subcat']

            if cat_name and cat_name not in group_map:
                g = StockGroup.objects.filter(
                    company=company, name__iexact=cat_name, is_deleted=False
                ).first()
                if not g:
                    # check global
                    g = StockGroup.objects.filter(
                        company__isnull=True, name__iexact=cat_name, is_deleted=False
                    ).first()
                if not g:
                    g = StockGroup.objects.create(
                        auto_id=get_auto_id(StockGroup),
                        creator=creator,
                        company=company,
                        name=cat_name
                    )
                group_map[cat_name] = g

            grp = group_map.get(cat_name)
            if grp and subcat_name and (cat_name, subcat_name) not in subgroup_map:
                sg = StockSubGroup.objects.filter(
                    company=company, group=grp, name__iexact=subcat_name, is_deleted=False
                ).first()
                if not sg:
                    sg = StockSubGroup.objects.filter(
                        company__isnull=True, group=grp, name__iexact=subcat_name, is_deleted=False
                    ).first()
                if not sg:
                    sg = StockSubGroup.objects.create(
                        auto_id=get_auto_id(StockSubGroup),
                        creator=creator,
                        company=company,
                        group=grp,
                        name=subcat_name
                    )
                subgroup_map[(cat_name, subcat_name)] = sg

        # Create/Update stock items
        created_count = 0
        updated_count = 0
        stock_ids = []

        # Current max auto_id
        current_max_auto_id = Stock.objects.all().aggregate(Max('auto_id'))['auto_id__max'] or 0

        for item in parsed_items:
            current_max_auto_id += 1
            grp = group_map.get(item['cat'])
            sg = subgroup_map.get((item['cat'], item['subcat']))

            # Check if stock already exists for this company
            existing = None
            if item['code']:
                existing = Stock.objects.filter(
                    company=company, product_code__iexact=item['code'], item_name__iexact=item['name'], is_deleted=False
                ).first()
            if not existing:
                existing = Stock.objects.filter(
                    company=company, item_name__iexact=item['name'], is_deleted=False
                ).first()

            if existing:
                # If existing has 0 qty and new has > 0, update qty
                if existing.quantity == 0 and item['qty'] > 0:
                    existing.quantity = item['qty']
                elif item['qty'] > 0:
                    existing.quantity += item['qty']

                if item['selling_rate'] > 0:
                    existing.selling_price = item['selling_rate']
                if item['purchase_rate'] > 0:
                    existing.purchase_rate = item['purchase_rate']
                if grp:
                    existing.group = grp
                if sg:
                    existing.sub_group = sg

                existing.save()
                stock_ids.append(existing.id)
                updated_count += 1
            else:
                stk = Stock(
                    auto_id=current_max_auto_id,
                    creator=creator,
                    company=company,
                    group=grp,
                    sub_group=sg,
                    product_code=item['code'],
                    part_number=item['code'],
                    item_name=item['name'],
                    country_of_origin='United Arab Emirates',
                    quantity=item['qty'],
                    unit=item['unit'],
                    base_unit=item['unit'],
                    purchase_rate=item['purchase_rate'],
                    selling_price=item['selling_rate'],
                    tax_percent=Decimal('5.00'),
                    vat_percent=Decimal('5.00'),
                    igst_percent=Decimal('5.00'),
                    cgst_percent=Decimal('0.00'),
                    sgst_percent=Decimal('0.00'),
                    is_trading=item['is_trading'],
                    is_operational=item['is_operational'],
                    expense_head=expense_head
                )
                stk.save()
                stock_ids.append(stk.id)
                created_count += 1

        # Now update all date_added and date_updated to 1st November 2026
        Stock.objects.filter(id__in=stock_ids).update(
            date_added=OPENING_DATE,
            date_updated=OPENING_DATE
        )

        print(f"Import Completed Successfully!")
        print(f"Created: {created_count} items")
        print(f"Updated/Consolidated: {updated_count} items")
        print(f"Total Stock Items in Company: {Stock.objects.filter(company=company, is_deleted=False).count()}")

        # Verify date_added on sample items
        sample = Stock.objects.filter(company=company, is_deleted=False).first()
        if sample:
            print(f"Sample Item: {sample.item_name} | Qty: {sample.quantity} | Date Added: {sample.date_added}")

if __name__ == '__main__':
    run_import()
