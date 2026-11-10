from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('booking_management', '0028_jobcardactivityoption'),
    ]

    operations = [
        migrations.AddField(
            model_name='jobquotation',
            name='inspection_details',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='jobquotationissue',
            name='activities',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
