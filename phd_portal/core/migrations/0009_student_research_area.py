from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_merge_20261009_0913'),
    ]

    operations = [
        migrations.AddField(
            model_name='student',
            name='research_area',
            field=models.CharField(blank=True, max_length=255),
        ),
    ]