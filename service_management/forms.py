from django import forms
from django.forms import TextInput, Select, Textarea, NumberInput, CheckboxInput
from .models import ServiceType, Service, JobCardCategory, JobCardService, JobCardIssue, InspectionCategory, InspectionItem
from client_management.models import Client

class ServiceTypeForm(forms.ModelForm):
    class Meta:
        model = ServiceType
        fields = [ 'name']
        widgets = {
            'name': TextInput(attrs={'class': 'form-control', 'placeholder': 'Service category name (e.g. Wash, Oil Change)'}),
        }
        
class ServiceForm(forms.ModelForm):
    class Meta:
        model = Service
        fields = ['service_type', 'name', 'sac_code', 'description', 'is_active']
        widgets = {
            'service_type': Select(attrs={'class': 'form-control'}),
            'name': TextInput(attrs={'class': 'form-control', 'placeholder': 'Service Name (e.g. Foam Wash)'}),
            'sac_code': TextInput(attrs={'class': 'form-control', 'placeholder': 'SAC Code (e.g. 998714)'}),
            'description': Textarea(attrs={'class': 'form-control', 'placeholder': 'Operation details...', 'rows': 3}),
            # 'duration': NumberInput(attrs={'class': 'form-control', 'placeholder': 'Minutes'}),
            'is_active': CheckboxInput(attrs={'class': 'form-check-input'})
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['service_type'].queryset = ServiceType.objects.filter(is_deleted=False)
        self.fields['service_type'].label = "Service Category"
        self.fields['service_type'].empty_label = "-- Select Service Category --"
        self.fields['sac_code'].required = False
        self.fields['sac_code'].label = "SAC Code"


class JobCardCategoryForm(forms.ModelForm):
    class Meta:
        model = JobCardCategory
        fields = ['name']
        widgets = {'name': TextInput(attrs={'class': 'form-control', 'placeholder': 'Category name'})}

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        matches = JobCardCategory.objects.filter(name__iexact=name, is_deleted=False)
        if self.instance.pk:
            matches = matches.exclude(pk=self.instance.pk)
        if matches.exists():
            raise forms.ValidationError('A Job Card category with this name already exists.')
        return name


class JobCardServiceForm(forms.ModelForm):
    class Meta:
        model = JobCardService
        fields = ['category', 'name']
        widgets = {
            'category': Select(attrs={'class': 'form-control'}),
            'name': TextInput(attrs={'class': 'form-control', 'placeholder': 'Service name'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].queryset = JobCardCategory.objects.filter(is_deleted=False)
        self.fields['category'].empty_label = '-- Select category --'

    def clean(self):
        cleaned = super().clean()
        category, name = cleaned.get('category'), cleaned.get('name', '').strip()
        if category and name:
            matches = JobCardService.objects.filter(category=category, name__iexact=name, is_deleted=False)
            if self.instance.pk:
                matches = matches.exclude(pk=self.instance.pk)
            if matches.exists():
                self.add_error('name', 'This service already exists in the selected category.')
        return cleaned


class JobCardIssueForm(forms.ModelForm):
    class Meta:
        model = JobCardIssue
        fields = ['category', 'service', 'name']
        widgets = {
            'category': Select(attrs={'class': 'form-control', 'id': 'id_category'}),
            'service': Select(attrs={'class': 'form-control', 'id': 'id_service'}),
            'name': TextInput(attrs={'class': 'form-control', 'placeholder': 'Issue name'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        categories = JobCardCategory.objects.filter(is_deleted=False)
        self.fields['category'].queryset = categories
        self.fields['category'].empty_label = '-- Select category --'
        self.fields['service'].queryset = JobCardService.objects.filter(is_deleted=False, category__in=categories)
        self.fields['service'].empty_label = '-- Select service --'

    def clean(self):
        cleaned = super().clean()
        category, service = cleaned.get('category'), cleaned.get('service')
        if category and service and service.category_id != category.id:
            self.add_error('service', 'Select a service that belongs to this category.')
        name = cleaned.get('name', '').strip()
        if category and service and name:
            matches = JobCardIssue.objects.filter(category=category, service=service, name__iexact=name, is_deleted=False)
            if self.instance.pk:
                matches = matches.exclude(pk=self.instance.pk)
            if matches.exists():
                self.add_error('name', 'This issue already exists for the selected service.')
        return cleaned


class InspectionCategoryForm(forms.ModelForm):
    class Meta:
        model = InspectionCategory
        fields = ['name', 'sort_order', 'is_active']
        widgets = {
            'name': TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Tyre & Wheels, Battery, Oil & Fluids'}),
            'sort_order': NumberInput(attrs={'class': 'form-control', 'placeholder': '0'}),
            'is_active': CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        matches = InspectionCategory.objects.filter(name__iexact=name, is_deleted=False)
        if self.instance.pk:
            matches = matches.exclude(pk=self.instance.pk)
        if matches.exists():
            raise forms.ValidationError('An inspection category with this name already exists.')
        return name


class InspectionItemForm(forms.ModelForm):
    class Meta:
        model = InspectionItem
        fields = ['category', 'name', 'input_type', 'unit', 'service', 'description', 'sort_order', 'is_active']
        widgets = {
            'category': Select(attrs={'class': 'form-control'}),
            'name': TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Battery Voltage, Front Brake Pads, Coolant Level'}),
            'input_type': Select(attrs={'class': 'form-control'}),
            'unit': TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. V, mm, psi'}),
            'service': Select(attrs={'class': 'form-control'}),
            'description': TextInput(attrs={'class': 'form-control', 'placeholder': 'Guidance / Notes for technician'}),
            'sort_order': NumberInput(attrs={'class': 'form-control', 'placeholder': '0'}),
            'is_active': CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].queryset = InspectionCategory.objects.filter(is_deleted=False)
        self.fields['category'].empty_label = '-- Select Category --'
        self.fields['service'].queryset = JobCardService.objects.filter(is_deleted=False)
        self.fields['service'].empty_label = '-- Select Optional Upsell Service --'
        self.fields['service'].required = False
        self.fields['unit'].required = False
        self.fields['description'].required = False

