from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_student_research_area'),
    ]

    operations = [
        migrations.AlterField(
            model_name='student',
            name='research_area',
            field=models.TextField(blank=True),
        ),
    ]