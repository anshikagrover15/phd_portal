import pandas as pd
from django.db import transaction

from .models import Offer, Student, Semester


COLUMN_ALIASES = {
    'sr': 'sr_no',
    'appl. no.': 'application_no',
    'appl no': 'application_no',
    'application no': 'application_no',
    'program': 'program',
    'discipline': 'discipline',
    'first name': 'first_name',
    'category': 'category',
    'dob': 'dob',
    'email': 'email',
    'altemail': 'alt_email',
    'alt email': 'alt_email',
    'city': 'city',
    'gender': 'gender',
    'yes/no': 'yes_no',
    'recipient': 'recipient',
    'email sent': 'email_sent',
    'attachment id 1': 'attachment_id_1',
    'attachment id 2': 'attachment_id_2',
    'attachment id 3': 'attachment_id_3',
}


def normalize_column_name(name):
    return (
        str(name)
        .strip()
        .lower()
        .replace('_', ' ')
    )


def import_offer_excel(uploaded_file, semester):
    try:
        df = pd.read_excel(uploaded_file)
    except Exception as exc:
        raise ValueError(f'Could not read Excel file: {exc}')

    # Normalize Excel column names
    normalized_columns = {}

    for column in df.columns:
        normalized = normalize_column_name(column)
        normalized_columns[column] = COLUMN_ALIASES.get(
            normalized,
            normalized
        )

    df = df.rename(columns=normalized_columns)

    if 'application_no' not in df.columns:
        raise ValueError(
            'Offer Excel must contain an "Appl. No." column.'
        )

    created = 0
    updated = 0
    skipped = 0
    errors = []

    for index, row in df.iterrows():

        application_no = str(
            row.get('application_no', '')
        ).strip()

        if not application_no or application_no == 'nan':
            skipped += 1
            continue

        try:
            with transaction.atomic():
                student = Student.objects.filter(
                    application_no=application_no,
                    semester=semester,
                ).first()

                if not student:
                    other = Student.objects.filter(
                        application_no=application_no
                    ).select_related('semester').first()
                    if other:
                        errors.append(
                            f'Row {index + 2}: {application_no} belongs to '
                            f'{other.semester}, not {semester}.'
                        )
                    else:
                        errors.append(
                            f'Row {index + 2}: Student {application_no} was not found.'
                        )
                    skipped += 1
                    continue

                offer = Offer.objects.filter(student=student).first()
                is_created = offer is None
                if is_created:
                    offer = Offer.create_for_student(student, semester=semester)

                sr_no = row.get('sr_no', '')
                if pd.notna(sr_no):
                    offer.sr_no = str(sr_no).strip()

                offer.save()

            if is_created:
                created += 1
            else:
                updated += 1

        except Exception as exc:
            errors.append(
                f'Row {index + 2}: {exc}'
            )
            skipped += 1

    return {
        'created': created,
        'updated': updated,
        'skipped': skipped,
        'errors': errors,
    }