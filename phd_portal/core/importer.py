import io
from datetime import datetime

import pandas as pd
from django.db import transaction

from .models import *

REQUIRED_COLUMNS = {
    'Application No': 'application_no',
    'Program': 'program',
    'Discipline': 'discipline',
    'First Name': 'first_name',
    'Last Name': 'last_name',
    'Application Status': 'status_of_application',
    'Category': 'category',
    'Dob': 'dob',
    'Gender': 'gender',
    'Email': 'email',
    'Peraddress1': 'permanent_address_line_1',
    'Peraddress2': 'address_line_2',
    'Percity': 'city',
    'Perpincode': 'pincode',
    'Perstate': 'state',
}


def _parse_excel_date(value):
    if pd.isna(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return pd.to_datetime(text).date()
        except Exception:
            return None
    try:
        return pd.to_datetime(value).date()
    except Exception:
        return None


def _clean_text(value):
    if pd.isna(value):
        return ''
    # Excel numeric cells (phone numbers, PIN codes) arrive as floats; 9876543210.0 must be stored as 9876543210.
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _coalesce(*values):
    for value in values:
        if value not in (None, ''):
            return value
    return ''


def import_master_excel(file_obj, semester=None):
    if semester is None:
        semester = Semester.objects.filter(is_active=True).first()
    if semester is None:
        raise ValueError('A semester is required before importing students.')

    workbook = pd.ExcelFile(file_obj)
    sheet_name = workbook.sheet_names[0]
    df = pd.read_excel(file_obj, sheet_name=sheet_name)

    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f'Missing required Excel columns: {missing}')

    summary = {
        'total_rows': 0,
        'imported': 0,
        'skipped_existing': 0,
        'invalid_rows': 0,
    }

    with transaction.atomic():
        for _, row in df.iterrows():
            summary['total_rows'] += 1
            application_no = _clean_text(row.get('Application No'))
            if not application_no:
                summary['invalid_rows'] += 1
                continue

            first_name = _clean_text(row.get('First Name'))
            middle_name = _clean_text(row.get('Middle Name'))
            last_name = _clean_text(row.get('Last Name'))
            full_name = ' '.join(part for part in [first_name, middle_name, last_name] if part)

            existing = Student.objects.filter(application_no=application_no).first()
            if existing:
                name_updates = {}
                if first_name and existing.first_name != first_name:
                    name_updates['first_name'] = first_name
                if middle_name and existing.middle_name != middle_name:
                    name_updates['middle_name'] = middle_name
                if last_name and existing.last_name != last_name:
                    name_updates['last_name'] = last_name
                if full_name and first_name and last_name and existing.full_name != full_name:
                    name_updates['full_name'] = full_name
                if name_updates:
                    for field, value in name_updates.items():
                        setattr(existing, field, value)
                    existing.save(update_fields=list(name_updates))

                research_area = _clean_text(row.get('Research Area'))
                if research_area and existing.research_area != research_area:
                    existing.research_area = research_area
                    existing.save(update_fields=['research_area'])
                if existing.semester_id is None:
                    # Student predates semester tracking; attach to this semester.
                    existing.semester = semester
                    existing.save(update_fields=['semester'])
                    summary['imported'] += 1
                else:
                    summary['skipped_existing'] += 1
                continue

            if not full_name:
                summary['invalid_rows'] += 1
                continue

            student = Student(
                semester=semester,
                application_no=application_no,
                program=_clean_text(row.get('Program')),
                discipline=_clean_text(row.get('Discipline')),
                research_area=_clean_text(row.get('Research Area')),
                first_name=first_name,
                middle_name=middle_name,
                last_name=last_name,
                full_name=full_name,
                category=_clean_text(row.get('Category')),
                dob=_parse_excel_date(row.get('Dob')),
                gender=_clean_text(row.get('Gender')),
                contact_no_1=_clean_text(row.get('Prephone')) or _clean_text(row.get('Premobile')),
                contact_no_2=_clean_text(row.get('Premobile')) or _clean_text(row.get('Prephone')),
                email=_clean_text(row.get('Email')),
                permanent_address_line_1=_coalesce(
                    _clean_text(row.get('Peraddress1')), _clean_text(row.get('Preaddress1'))
                ),
                address_line_2=_coalesce(
                    _clean_text(row.get('Peraddress2')), _clean_text(row.get('Preaddress2'))
                ),
                city=_coalesce(_clean_text(row.get('Percity')), _clean_text(row.get('Precity'))),
                pincode=_coalesce(_clean_text(row.get('Perpincode')), _clean_text(row.get('Prepincode'))),
                state=_coalesce(_clean_text(row.get('Perstate')), _clean_text(row.get('Prestate'))),
                status_of_application=_clean_text(row.get('Application Status')),
                iitgn_email_id=_clean_text(row.get('Gmail ID')),
            )

            try:
                student.full_clean()
            except Exception:
                summary['invalid_rows'] += 1
                continue

            student.save()
            summary['imported'] += 1

    return summary
