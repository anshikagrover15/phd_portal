"""Strip the trailing ".0" that earlier imports left on phone numbers and PIN codes.

    python manage.py clean_numeric_text          # preview
    python manage.py clean_numeric_text --apply  # save
"""
import re

from django.core.management.base import BaseCommand

from core.models import Student

FIELDS = ('contact_no_1', 'contact_no_2', 'pincode')
PATTERN = re.compile(r'^(\d+)\.0+$')


class Command(BaseCommand):
    help = 'Remove the ".0" suffix from numeric text fields on students.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Save the changes (default is a dry run).')

    def handle(self, *args, **opts):
        changed = 0
        for student in Student.objects.all():
            updates = {}
            for field in FIELDS:
                match = PATTERN.match(getattr(student, field) or '')
                if match:
                    updates[field] = match.group(1)
            if updates:
                changed += 1
                if opts['apply']:
                    Student.objects.filter(pk=student.pk).update(**updates)
        verb = 'Updated' if opts['apply'] else 'Would update'
        self.stdout.write(f'{verb} {changed} student(s).')
