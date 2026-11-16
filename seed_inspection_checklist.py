import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wash_pilot.settings')
django.setup()

from service_management.models import InspectionCategory, InspectionItem, JobCardService
from core.functions import get_auto_id

def seed_inspection_master():
    print("🌱 Seeding Dynamic Inspection Master...")

    checklist_data = [
        {
            'name': 'Tyre & Wheels',
            'icon': 'tire_repair',
            'sort_order': 1,
            'items': [
                {'name': 'Tyre Pressure (FL, FR, RL, RR)', 'input_type': 'measurement', 'unit': 'psi', 'sort_order': 1, 'service_hint': 'Tyre'},
                {'name': 'Tyre Tread Depth & Wear', 'input_type': 'measurement', 'unit': 'mm', 'sort_order': 2, 'service_hint': 'Tyre'},
                {'name': 'Wheel Alignment & Balancing', 'input_type': 'rag', 'unit': '', 'sort_order': 3, 'service_hint': 'Alignment'},
                {'name': 'Wheel Rim Condition & Scratches', 'input_type': 'rag', 'unit': '', 'sort_order': 4, 'service_hint': 'Wheel'},
            ]
        },
        {
            'name': 'Oil & Fluids',
            'icon': 'opacity',
            'sort_order': 2,
            'items': [
                {'name': 'Engine Oil Level & Quality', 'input_type': 'rag', 'unit': '', 'sort_order': 1, 'service_hint': 'Oil'},
                {'name': 'Brake Fluid Level & Moisture', 'input_type': 'rag', 'unit': '', 'sort_order': 2, 'service_hint': 'Brake'},
                {'name': 'Coolant Level & Radiator Condition', 'input_type': 'rag', 'unit': '', 'sort_order': 3, 'service_hint': 'Coolant'},
                {'name': 'Windshield Washer Fluid', 'input_type': 'yes_no', 'unit': '', 'sort_order': 4, 'service_hint': ''},
            ]
        },
        {
            'name': 'Brakes & Suspension',
            'icon': 'settings',
            'sort_order': 3,
            'items': [
                {'name': 'Front Brake Pads Condition', 'input_type': 'rag', 'unit': '', 'sort_order': 1, 'service_hint': 'Brake'},
                {'name': 'Rear Brake Pads / Shoes Condition', 'input_type': 'rag', 'unit': '', 'sort_order': 2, 'service_hint': 'Brake'},
                {'name': 'Brake Discs / Rotors Surface', 'input_type': 'rag', 'unit': '', 'sort_order': 3, 'service_hint': 'Brake'},
                {'name': 'Shock Absorbers & Struts Leakage', 'input_type': 'rag', 'unit': '', 'sort_order': 4, 'service_hint': 'Suspension'},
            ]
        },
        {
            'name': 'Battery & Electrical',
            'icon': 'battery_charging_full',
            'sort_order': 4,
            'items': [
                {'name': 'Battery Voltage & Cranking Health', 'input_type': 'measurement', 'unit': 'V', 'sort_order': 1, 'service_hint': 'Battery'},
                {'name': 'Battery Terminals & Acid Corrosion', 'input_type': 'rag', 'unit': '', 'sort_order': 2, 'service_hint': 'Battery'},
                {'name': 'Headlights, Taillights & Indicators', 'input_type': 'yes_no', 'unit': '', 'sort_order': 3, 'service_hint': 'Electrical'},
                {'name': 'Horn & Wiper Blades Performance', 'input_type': 'yes_no', 'unit': '', 'sort_order': 4, 'service_hint': 'Wiper'},
            ]
        },
        {
            'name': 'AC & Climate Control',
            'icon': 'ac_unit',
            'sort_order': 5,
            'items': [
                {'name': 'AC Cooling Temp & Airflow', 'input_type': 'rag', 'unit': '', 'sort_order': 1, 'service_hint': 'AC'},
                {'name': 'Cabin AC Filter Dust & Odour', 'input_type': 'rag', 'unit': '', 'sort_order': 2, 'service_hint': 'AC'},
            ]
        },
        {
            'name': 'Detailing & Body',
            'icon': 'brush',
            'sort_order': 6,
            'items': [
                {'name': 'Paint Surface Swirls & Oxidation', 'input_type': 'rag', 'unit': '', 'sort_order': 1, 'service_hint': 'Detailing'},
                {'name': 'Interior Leather / Fabric Stains', 'input_type': 'rag', 'unit': '', 'sort_order': 2, 'service_hint': 'Interior'},
                {'name': 'Underbody Rust & Corrosion Check', 'input_type': 'rag', 'unit': '', 'sort_order': 3, 'service_hint': 'Underbody'},
            ]
        },
    ]

    for cat_data in checklist_data:
        cat, created = InspectionCategory.objects.get_or_create(
            name=cat_data['name'],
            defaults={
                'auto_id': get_auto_id(InspectionCategory),
                'icon': cat_data['icon'],
                'sort_order': cat_data['sort_order'],
                'is_active': True,
            }
        )
        if not created:
            cat.icon = cat_data['icon']
            cat.sort_order = cat_data['sort_order']
            cat.is_active = True
            cat.save()

        for item_data in cat_data['items']:
            # Find matching upsell service if available
            upsell_service = None
            if item_data.get('service_hint'):
                upsell_service = JobCardService.objects.filter(
                    name__icontains=item_data['service_hint'],
                    is_deleted=False
                ).first()

            item, i_created = InspectionItem.objects.get_or_create(
                category=cat,
                name=item_data['name'],
                defaults={
                    'auto_id': get_auto_id(InspectionItem),
                    'input_type': item_data['input_type'],
                    'unit': item_data['unit'],
                    'service': upsell_service,
                    'sort_order': item_data['sort_order'],
                    'is_active': True,
                }
            )
            if not i_created:
                item.input_type = item_data['input_type']
                item.unit = item_data['unit']
                if upsell_service and not item.service:
                    item.service = upsell_service
                item.sort_order = item_data['sort_order']
                item.is_active = True
                item.save()

    print(f"✅ Seeding complete: {InspectionCategory.objects.filter(is_deleted=False).count()} categories, {InspectionItem.objects.filter(is_deleted=False).count()} items.")

if __name__ == '__main__':
    seed_inspection_master()
