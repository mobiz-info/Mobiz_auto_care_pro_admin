import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wash_pilot.settings')
django.setup()

from service_management.models import ServiceType, Service, BranchService, CompanyService, BranchServiceCategory
from client_management.models import Branch
from core.functions import get_auto_id

enabled_bscs = BranchServiceCategory.objects.filter(is_enabled=True, is_deleted=False)
print(f"Total enabled BranchServiceCategory entries: {enabled_bscs.count()}")

synced_bs = 0
synced_cs = 0

for bsc in enabled_bscs:
    branch = bsc.branch
    st = bsc.service_type
    if not branch or not st:
        continue
    company = branch.company
    services = Service.objects.filter(service_type=st, is_active=True, is_deleted=False)

    for svc in services:
        if company:
            cs, created = CompanyService.objects.get_or_create(
                company=company,
                service=svc,
                defaults={'auto_id': get_auto_id(CompanyService), 'is_enabled': True}
            )
            if not cs.is_enabled:
                cs.is_enabled = True
                cs.save()
                synced_cs += 1

        bs, created = BranchService.objects.get_or_create(
            branch=branch,
            service=svc,
            defaults={'auto_id': get_auto_id(BranchService), 'is_enabled': True}
        )
        if not bs.is_enabled:
            bs.is_enabled = True
            bs.save()
            synced_bs += 1

print(f"Sync complete. Re-enabled/created {synced_bs} BranchServices, {synced_cs} CompanyServices.")
