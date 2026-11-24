from django.contrib import admin
from .models import Customer, CustomerVehicle, Staff, StaffPayslip

@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'email', 'date_added')
    search_fields = ('name', 'phone', 'email')
    ordering = ('-auto_id',)

@admin.register(CustomerVehicle)
class CustomerVehicleAdmin(admin.ModelAdmin):
    list_display = ('vehicle_number', 'customer', 'vehicle_type_model', 'fuel_type', 'date_added')
    search_fields = ('vehicle_number', 'customer__name', 'customer__phone')
    list_filter = ('fuel_type', 'wheel_type')
    ordering = ('-auto_id',)

@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    list_display = ('name', 'employee_id', 'branch', 'designation', 'salary_mode', 'monthly_salary', 'daily_wage')
    search_fields = ('name', 'employee_id', 'phone')
    list_filter = ('salary_mode', 'designation', 'branch')

@admin.register(StaffPayslip)
class StaffPayslipAdmin(admin.ModelAdmin):
    list_display = ('payslip_number', 'staff', 'salary_month', 'gross_salary', 'advance_deduction', 'net_salary', 'paid_amount', 'balance_amount', 'payment_status')
    search_fields = ('payslip_number', 'staff__name', 'staff__employee_id')
    list_filter = ('payment_status', 'salary_month', 'branch')