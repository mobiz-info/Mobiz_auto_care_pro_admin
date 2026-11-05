from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('booking_management', '0025_jobcardpartitem_warranty_years'),
    ]

    operations = [
        migrations.AddField(
            model_name='jobcard',
            name='inspection_details',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
