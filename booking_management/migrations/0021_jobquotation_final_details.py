from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('booking_management', '0020_jobquotationitem_discount_issue_link'),
        ('client_management', '0070_customer_pan_number'),
    ]

    operations = [
        migrations.AddField(
            model_name='jobquotation',
            name='internal_notes',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='jobquotation',
            name='inspection_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='jobquotation',
            name='tentative_delivery_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='jobquotation',
            name='prepared_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='prepared_job_quotations', to='client_management.staff'),
        ),
        migrations.AddField(
            model_name='jobquotationitem',
            name='line_type',
            field=models.CharField(default='legacy', max_length=30),
        ),
        migrations.AddField(
            model_name='jobquotationitem',
            name='remarks',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='jobquotationextra',
            name='line_type',
            field=models.CharField(default='legacy', max_length=30),
        ),
    ]
