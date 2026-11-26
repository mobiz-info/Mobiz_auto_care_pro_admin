from django.db import migrations
from datetime import date


def consolidate_salary_expense_heads(apps, schema_editor):
    ExpenseHead = apps.get_model('master', 'ExpenseHead')
    Expense = apps.get_model('master', 'Expense')
    ExpenseEntry = apps.get_model('master', 'ExpenseEntry')

    all_heads = ExpenseHead.objects.filter(is_deleted=False)
    company_ids = set(all_heads.values_list('company_id', flat=True))

    for comp_id in company_ids:
        # Find or ensure 'Salary & Wages' for this company
        sw_head = ExpenseHead.objects.filter(
            company_id=comp_id,
            name__iexact='Salary & Wages',
            is_deleted=False
        ).first()

        if not sw_head:
            sw_head = ExpenseHead.objects.filter(
                company_id=comp_id,
                name__iexact='Salary & Wages'
            ).first()
            if sw_head:
                sw_head.is_deleted = False
                sw_head.save()

        # Migrate all entries from 'Salary Advance' heads
        adv_heads = ExpenseHead.objects.filter(
            company_id=comp_id,
            name__iexact='Salary Advance',
            is_deleted=False
        )
        for adv_h in adv_heads:
            if sw_head:
                for exp in Expense.objects.filter(expense_head=adv_h):
                    existing_sw_exp = Expense.objects.filter(expense_head=sw_head, name=exp.name).first()
                    if existing_sw_exp and existing_sw_exp != exp:
                        ExpenseEntry.objects.filter(expense=exp).update(
                            expense=existing_sw_exp,
                            salary_payment_type='ADVANCE'
                        )
                        exp.is_deleted = True
                        exp.save()
                    else:
                        exp.expense_head = sw_head
                        exp.save()
                        ExpenseEntry.objects.filter(expense=exp).filter(salary_payment_type__isnull=True).update(
                            salary_payment_type='ADVANCE'
                        )
            adv_h.is_deleted = True
            adv_h.save()

        # Migrate all entries from 'Salary' heads
        sal_heads = ExpenseHead.objects.filter(
            company_id=comp_id,
            name__iexact='Salary',
            is_deleted=False
        )
        for sal_h in sal_heads:
            if sw_head:
                for exp in Expense.objects.filter(expense_head=sal_h):
                    existing_sw_exp = Expense.objects.filter(expense_head=sw_head, name=exp.name).first()
                    if existing_sw_exp and existing_sw_exp != exp:
                        ExpenseEntry.objects.filter(expense=exp).update(
                            expense=existing_sw_exp,
                            salary_payment_type='SALARY'
                        )
                        exp.is_deleted = True
                        exp.save()
                    else:
                        exp.expense_head = sw_head
                        exp.save()
                        ExpenseEntry.objects.filter(expense=exp).filter(salary_payment_type__isnull=True).update(
                            salary_payment_type='SALARY'
                        )
            sal_h.is_deleted = True
            sal_h.save()

        if sw_head:
            for entry in ExpenseEntry.objects.filter(expense__expense_head=sw_head, salary_month__isnull=True, expense_date__isnull=False):
                entry.salary_month = date(entry.expense_date.year, entry.expense_date.month, 1)
                entry.save()


def reverse_func(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('master', '0038_expenseentry_salary_month_and_more'),
    ]

    operations = [
        migrations.RunPython(consolidate_salary_expense_heads, reverse_func),
    ]
