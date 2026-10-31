import re
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import pandas as pd
from django.db import transaction
from django.utils import timezone

from .models import *

SUCCESS_STATUS = 'TXN_SUCCESS'
# The payment gateway reports local (Indian) time.
GATEWAY_TZ = ZoneInfo('Asia/Kolkata')

# Normalised header -> internal key. Headers are compared lowercase with punctuation
# dropped, so 'Roll No/Application No' and 'Roll No. Application No.' both match.
COLUMN_ALIASES = {
    'roll no application no': 'application_no',
    'application no': 'application_no',
    'roll no': 'application_no',
    'status': 'status',
    'name': 'name',
    'email': 'email',
    'email id': 'email',
    'amount': 'amount',
    'date and time': 'paid_on',
    'date time': 'paid_on',
    'order id': 'order_id',
}
REQUIRED_KEYS = {'application_no', 'status', 'amount'}


def _norm_header(value):
    return re.sub(r'[^a-z0-9]+', ' ', str(value).lower()).strip()


def _clean_text(value):
    if pd.isna(value):
        return ''
    text = str(value).strip()
    # Excel numeric cells (e.g. 19310001) arrive as floats like "19310001.0".
    if re.fullmatch(r'\d+\.0', text):
        text = text[:-2]
    return text


def _parse_amount(value):
    try:
        return Decimal(str(value).replace(',', '').strip())
    except (InvalidOperation, ValueError):
        return None


def _parse_paid_on(value):
    if value is None or pd.isna(value) or not str(value).strip():
        return None
    try:
        # Gateway exports are year-first (2026-07-01); hand-typed dates are Indian day-first
        # (01-07-2026). dayfirst=True would misread 2026-07-01 as 7 January, so only use it
        # when the text does not start with the year.
        year_first = not isinstance(value, str) or re.match(r'\s*\d{4}', value)
        parsed = pd.to_datetime(value, dayfirst=not year_first)
    except (ValueError, TypeError):
        return None
    if pd.isna(parsed):
        return None
    parsed = parsed.to_pydatetime()
    return timezone.make_aware(parsed, GATEWAY_TZ) if timezone.is_naive(parsed) else parsed


def _order_number(order_id):
    """Numeric part of an order id (ORD26063477 -> 26063477); ids grow over time."""
    digits = re.sub(r'\D', '', order_id)
    return int(digits) if digits else 0


def _payment_sort_key(payment):
    """Earliest first: by payment time, then order id, then row; unknown times sort last."""
    paid_on = payment['paid_on']
    return (paid_on is None, paid_on or 0, _order_number(payment['order_id']), payment['row'])


def _is_earlier(paid_on, current_paid_on):
    return paid_on is not None and (current_paid_on is None or paid_on < current_paid_on)


def _normalise_name(value):
    return re.sub(r'\s+', ' ', value).strip().lower()


def _build_lookups(offers):
    """Index offered students by application no / roll no / email / name.

    Email and name can be shared by several students, so those indexes keep a list
    and are only used when they identify exactly one offer.
    """
    by_key = {'application_no': {}, 'roll_no': {}, 'email': {}, 'name': {}}
    for offer in offers:
        student = offer.student
        by_key['application_no'].setdefault(student.application_no.strip().lower(), []).append(offer)
        if offer.roll_no.strip():
            by_key['roll_no'].setdefault(offer.roll_no.strip().lower(), []).append(offer)
        for email in (student.email, student.iitgn_email_id):
            if email.strip():
                by_key['email'].setdefault(email.strip().lower(), []).append(offer)
        by_key['name'].setdefault(_normalise_name(student.full_name), []).append(offer)
    return by_key


def _match_offer(lookups, application_no, email, name):
    """Return (offer, method) or (None, reason)."""
    attempts = [
        ('application_no', application_no.lower(), 'application no'),
        ('roll_no', application_no.lower(), 'roll no'),
        ('email', email.lower(), 'email'),
        ('name', _normalise_name(name), 'name'),
    ]
    ambiguous = False
    for key, value, label in attempts:
        if not value:
            continue
        found = lookups[key].get(value, [])
        if len(found) == 1:
            return found[0], label
        if len(found) > 1:
            ambiguous = True
    return None, 'ambiguous match' if ambiguous else 'not in offered list'


def import_fees_excel(file_obj, semester=None):
    """Mark offers paid from a payment-gateway export and record each student's first payment.

    Only TXN_SUCCESS rows count. Every matched offer gets fees_paid=True and
    fees_amount = the sum of its successful payments in this file. first_fees_amount
    is the earliest payment by date and time (order id breaks ties), and a later
    import only replaces it with a payment made even earlier. Rows that match nobody
    in the offered list are reported, not imported.
    """
    df = pd.read_excel(file_obj, sheet_name=0, dtype=object)
    df = df.rename(columns={col: COLUMN_ALIASES[_norm_header(col)] for col in df.columns if _norm_header(col) in COLUMN_ALIASES})

    missing = REQUIRED_KEYS - set(df.columns)
    if missing:
        raise ValueError(f'Missing required columns in fees file: {sorted(missing)}')

    offers = Offer.objects.select_related('student')
    if semester is not None:
        offers = offers.filter(semester=semester)
    lookups = _build_lookups(offers)

    summary = {'total_rows': 0, 'updated': 0, 'not_successful': 0, 'invalid_rows': 0, 'unmatched': []}
    paid = {}  # offer pk -> {'offer', 'payments', 'methods'}

    for index, row in df.iterrows():
        summary['total_rows'] += 1
        excel_row = index + 2  # +1 for 0-based, +1 for the header row
        application_no = _clean_text(row.get('application_no'))
        name = _clean_text(row.get('name')) if 'name' in df.columns else ''
        email = _clean_text(row.get('email')) if 'email' in df.columns else ''

        if not any([application_no, name, email]):
            summary['invalid_rows'] += 1
            continue
        if _clean_text(row.get('status')).upper() != SUCCESS_STATUS:
            summary['not_successful'] += 1
            continue
        amount = _parse_amount(row.get('amount'))
        if amount is None:
            summary['invalid_rows'] += 1
            continue

        offer, method = _match_offer(lookups, application_no, email, name)
        if offer is None:
            summary['unmatched'].append({
                'row': excel_row,
                'application_no': application_no,
                'name': name,
                'amount': amount,
                'reason': method,
            })
            continue
        entry = paid.setdefault(offer.pk, {'offer': offer, 'payments': [], 'methods': []})
        entry['payments'].append({
            'amount': amount,
            'paid_on': _parse_paid_on(row.get('paid_on')) if 'paid_on' in df.columns else None,
            'order_id': _clean_text(row.get('order_id')) if 'order_id' in df.columns else '',
            'row': excel_row,
        })
        entry['methods'].append(method)

    with transaction.atomic():
        for entry in paid.values():
            offer = entry['offer']
            first = min(entry['payments'], key=_payment_sort_key)
            offer.fees_paid = True
            offer.fees_amount = sum((p['amount'] for p in entry['payments']), Decimal('0'))
            if offer.first_fees_amount is None or _is_earlier(first['paid_on'], offer.first_fees_paid_on):
                offer.first_fees_amount = first['amount']
                offer.first_fees_paid_on = first['paid_on']
            offer.save(update_fields=['fees_paid', 'fees_amount', 'first_fees_amount', 'first_fees_paid_on'])
            summary['updated'] += 1

    summary['by_name'] = sum(1 for entry in paid.values() if set(entry['methods']) == {'name'})
    return summary
