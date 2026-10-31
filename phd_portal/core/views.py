from functools import wraps
from itertools import groupby

from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render, resolve_url
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Exists, OuterRef, Q
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from .offer_importer import import_offer_excel
from .models import *
from .forms import *
from .importer import import_master_excel
from .fees_importer import import_fees_excel
from django.views.decorators.http import require_POST
from datetime import date
from django.core.validators import validate_email


def superuser_required(view_func):
    """Require a logged-in superuser. Anonymous users go to login; everyone else gets a 403."""
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return wrapper

class PortalLoginView(LoginView):
    """Superusers land on the dashboard, faculty on their live sheet."""

    def get_default_redirect_url(self):
        return resolve_url('home' if self.request.user.is_superuser else 'live-sheet')

@superuser_required
def offer_list(request):
    semester_id = request.GET.get('semester')
    queryset = Offer.objects.select_related('student', 'semester').order_by('semester__name', 'student__application_no')
    if semester_id:
        queryset = queryset.filter(semester_id=semester_id)

    semesters = Semester.objects.all().order_by('name')
    return render(request, 'offers/offer_list.html', {
        'title': 'Offers',
        'offers': queryset,
        'semesters': semesters,
        'selected_semester_id': semester_id,
    })



@superuser_required
def student_list(request):
    """Master data: every student, with searchable field filters and offer status."""
    active_semester = Semester.objects.filter(is_active=True).first()
    semester_param = request.GET.get('semester')
    if semester_param is None:
        semester_param = str(active_semester.pk) if active_semester else 'all'
    query = request.GET.get('q', '').strip()
    offer_filter = request.GET.get('offer', '')
    program_filter = request.GET.getlist('program')
    discipline_filter = request.GET.getlist('discipline')
    category_filter = request.GET.getlist('category')

    students = Student.objects.select_related('semester').annotate(
        has_offer=Exists(Offer.objects.filter(student=OuterRef('pk')))
    ).order_by('full_name', 'application_no')
    if semester_param != 'all':
        students = students.filter(semester_id=semester_param)
    if query:
        students = students.filter(
            Q(full_name__icontains=query)
            | Q(application_no__icontains=query)
            | Q(email__icontains=query)
            | Q(discipline__icontains=query)
            | Q(program__icontains=query)
            | Q(category__icontains=query)
            | Q(contact_no_1__icontains=query)
            | Q(contact_no_2__icontains=query)
        )
    if program_filter:
        students = students.filter(program__in=program_filter)
    if discipline_filter:
        students = students.filter(discipline__in=discipline_filter)
    if category_filter:
        students = students.filter(category__in=category_filter)
    if offer_filter == 'offered':
        students = students.filter(has_offer=True)
    elif offer_filter == 'not_offered':
        students = students.filter(has_offer=False)

    semesters = list(Semester.objects.all().order_by('name'))
    programs = sorted({value.strip() for value in Student.objects.values_list('program', flat=True) if value and value.strip()})
    disciplines = sorted({value.strip() for value in Student.objects.values_list('discipline', flat=True) if value and value.strip()})
    categories = sorted({value.strip() for value in Student.objects.values_list('category', flat=True) if value and value.strip()})

    return render(request, 'students/student_list.html', {
        'title': 'All applicants',
        'students': students,
        'semesters': semesters,
        'selected_semester_id': semester_param,
        'programs': programs,
        'disciplines': disciplines,
        'categories': categories,
        'program_filter': program_filter,
        'discipline_filter': discipline_filter,
        'category_filter': category_filter,
        'q': query,
        'offer_filter': offer_filter,
        'result_count': students.count(),
    })

@superuser_required
def add_student_to_offers(request, student_id):
    if request.method == 'POST':
        try:
            student = Student.objects.get(pk=student_id)
            offer = Offer.create_for_student(student)
            messages.success(request, f'{student.full_name} was added to the offered list ({offer.semester.name}).')
        except Student.DoesNotExist:
            messages.error(request, 'Student not found.')
        except ValueError as exc:
            messages.error(request, str(exc))

    next_url = request.POST.get('next', '')
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = reverse('student-list')
    return redirect(next_url)

@superuser_required
@login_required

def delete_student(request, student_id):
    if request.method != 'POST':
        return redirect('student-list')

    try:
        student = Student.objects.get(pk=student_id)
        name = student.full_name
        application_no = student.application_no
        student.delete()
        messages.success(request, f'{name} ({application_no}) was deleted.')
    except Student.DoesNotExist:
        messages.error(request, 'Student not found.')

    return redirect('student-list')

@superuser_required
def edit_student(request, student_id):
    student = get_object_or_404(Student, pk=student_id)

    if request.method == 'POST':
        form = StudentForm(request.POST, instance=student)
        if form.is_valid():
            form.save()
            messages.success(request, f'{student.full_name} was updated.')
            return redirect('student-list')
    else:
        form = StudentForm(instance=student)

    return render(request, 'students/edit_student.html', {
        'title': 'Edit Student',
        'student': student,
        'form': form,
    })

@superuser_required
def home(request: HttpRequest) -> HttpResponse:
    active_semester = Semester.objects.filter(is_active=True).first()
    semesters = Semester.objects.all().order_by('name')
    semester_param = request.GET.get('semester')

    if semester_param == 'all':
        selected_semester = None
    elif semester_param:
        selected_semester = semesters.filter(pk=semester_param).first() or active_semester
    else:
        selected_semester = active_semester

    offers = Offer.objects.select_related('student', 'semester').order_by('student__application_no')
    if selected_semester:
        offers = offers.filter(semester=selected_semester)

    total_offers = offers.count()
    paid_offers = offers.filter(fees_paid=True).count()
    selected_semester_id = str(selected_semester.pk) if selected_semester else 'all'

    return render(request, 'core/dashboard.html', {
        'title': 'Dashboard',
        'active_semester': active_semester,
        'semesters': semesters,
        'selected_semester': selected_semester,
        'selected_semester_id': selected_semester_id,
        'offers': offers,
        'total_offers': total_offers,
        'paid_offers': paid_offers,
        'unpaid_offers': total_offers - paid_offers,
    })

NOT_SET = '__none__'


def _clean(value):
    """Trim and collapse whitespace so 'A  B ' and 'A B' land in the same group."""
    return ' '.join((value or '').split())


def _branch_key(offer):
    return _clean(offer.student.discipline) or NOT_SET


def _program_key(offer):
    return _clean(offer.student.program) or NOT_SET


def _sub_programme_key(offer):
    return _clean(offer.student.sub_programme) or NOT_SET


def _name_sort(key):
    return (key == NOT_SET, key.casefold())  # named groups A-Z, "not set" last


def _dis_sr_sort_key(offer):
    """Orders 'AI 2' before 'AI 10' (plain string sorting would put 'AI 10' first)."""
    prefix, _, number = offer.dis_sr_no.strip().rpartition(' ')
    return (offer.semester.name, prefix, int(number) if number.isdigit() else 0, offer.dis_sr_no)


def _options(keys, not_set_label):
    options = [(key, key) for key in sorted((k for k in keys if k != NOT_SET), key=str.casefold)]
    if NOT_SET in keys:
        options.append((NOT_SET, not_set_label))
    return options

@login_required
def live_sheet(request):
    """Open to superusers and to the one faculty account only: every branch, grouped
    branch-wise, with multi-select semester / programme / branch filters."""
    if not (request.user.is_superuser or hasattr(request.user, 'faculty_account')):
        raise PermissionDenied
    submitted = 'filtered' in request.GET

    all_offers = list(Offer.objects.select_related('student', 'semester'))

    semesters = list(Semester.objects.all().order_by('name'))
    semester_options = [(str(sem.id), sem.name) for sem in semesters]
    program_options = _options({_program_key(o) for o in all_offers}, 'Not specified')
    branch_options = _options({_branch_key(o) for o in all_offers}, 'Not specified')

    active = next((sem for sem in semesters if sem.is_active), None)
    default_semesters = {str(active.id)} if active else {value for value, _ in semester_options}

    def _selected(param, options, default):
        valid = {value for value, _ in options}
        if not submitted:
            return default & valid
        return set(request.GET.getlist(param)) & valid  # drops stale / hand-edited values

    selected_semesters = _selected('semester', semester_options, default_semesters)
    selected_programs = _selected('program', program_options, {v for v, _ in program_options})
    selected_branches = _selected('branch', branch_options, {v for v, _ in branch_options})

    rows = [
        o for o in all_offers
        if str(o.semester_id) in selected_semesters
        and _program_key(o) in selected_programs
        and _branch_key(o) in selected_branches
    ]

    def _field(name, label, all_label, options, selected):
        return {
            'name': name,
            'label': label,
            'all_label': all_label,
            'options': [
                {'value': value, 'label': text, 'checked': value in selected}
                for value, text in options
            ],
            'selected_count': len(selected),
            'total_count': len(options),
        }

    filter_fields = [
        _field('semester', 'Semester', 'All semesters', semester_options, selected_semesters),
        _field('program', 'Programme', 'All programmes', program_options, selected_programs),
        _field('branch', 'Discipline', 'All disciplines', branch_options, selected_branches),
    ]

    rows.sort(key=lambda o: (_name_sort(_branch_key(o)), _dis_sr_sort_key(o)))
    for sr_no, offer in enumerate(rows, start=1):
        offer.live_sheet_sr_no = sr_no

    groups = []
    for branch_key, branch_rows in groupby(rows, key=_branch_key):
        branch_rows = list(branch_rows)
        groups.append({
            'branch': 'Not specified' if branch_key == NOT_SET else branch_key,
            'count': len(branch_rows),
            'offers': branch_rows,
        })

    return render(request, 'faculty/live_sheet.html', {
        'title': 'Faculty Live Sheet',
        'groups': groups,
        'total': len(rows),
        'filter_fields': filter_fields,
    })

@superuser_required
def faculty_account(request):
    """Superuser-only page to create the faculty login and see / change its credentials."""
    account = FacultyAccount.current()
    if request.method == 'POST':
        form = FacultyAccountForm(request.POST, account=account)
        if form.is_valid():
            form.save()
            return redirect(f"{reverse('faculty-account')}?saved=1")
    else:
        form = FacultyAccountForm(account=account)

    return render(request, 'faculty/faculty_account.html', {
        'title': 'Faculty Account',
        'account': account,
        'form': form,
        'saved': request.GET.get('saved') == '1',
    })

@superuser_required
def semester_list(request):
    semesters = Semester.objects.all().order_by('name')
    return render(request, 'semesters/semester_list.html', {
        'title': 'Semesters',
        'semesters': semesters,
    })

@superuser_required
def toggle_semester_active(request, semester_id):
    if request.method == 'POST':
        try:
            semester = Semester.objects.get(pk=semester_id)
        except Semester.DoesNotExist:
            messages.error(request, 'Semester not found.')
            return redirect('semester-list')

        if semester.is_active:
            semester.is_active = False
            semester.save()
            messages.success(request, f'{semester.name} is now inactive.')
        else:
            # Only one semester may be active, so switch any other one off.
            Semester.objects.filter(is_active=True).update(is_active=False)
            semester.is_active = True
            semester.save()
            messages.success(request, f'{semester.name} is now the active semester.')
    return redirect('semester-list')

@superuser_required
def import_fees_status(request):
    summary = None
    error = None
    semesters = Semester.objects.all().order_by('name')
    selected_semester_id = request.POST.get('semester') or request.GET.get('semester') or ''

    if request.method == 'POST':
        uploaded_file = request.FILES.get('excel_file')
        if not uploaded_file:
            error = 'Please select an Excel file to upload.'
        else:
            try:
                semester = Semester.objects.filter(pk=selected_semester_id).first() if selected_semester_id else None
                summary = import_fees_excel(uploaded_file, semester=semester)
            except ValueError as exc:
                error = str(exc)
            except Exception as exc:
                error = f'Import failed: {exc}'

    return render(request, 'offers/import_fees.html', {
        'title': 'Import fees',
        'summary': summary,
        'error': error,
        'semesters': semesters,
        'selected_semester_id': selected_semester_id,
    })

@superuser_required
def import_student_excel(request):
    summary = None
    error = None
    semesters = Semester.objects.all().order_by('name')
    selected_semester_id = request.POST.get('semester') or request.GET.get('semester')

    if request.method == 'POST':
        uploaded_file = request.FILES.get('excel_file')
        if not selected_semester_id:
            error = 'Please select a semester before importing students.'
        elif not uploaded_file:
            error = 'Please select an Excel file to upload.'
        else:
            try:
                semester = Semester.objects.get(pk=selected_semester_id)
                summary = import_master_excel(uploaded_file, semester=semester)
            except ValueError as exc:
                error = str(exc)
            except Semester.DoesNotExist:
                error = 'Selected semester does not exist.'
            except Exception as exc:
                error = f'Import failed: {exc}'

    return render(request, 'students/import_student.html', {
        'title': 'Import applicants',
        'summary': summary,
        'error': error,
        'semesters': semesters,
        'selected_semester_id': selected_semester_id,
    })

@superuser_required
def add_semester(request):
    if request.method == 'POST':
        form = SemesterForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Semester created successfully.')
            return redirect('semester-list')
    else:
        form = SemesterForm()

    return render(request, 'semesters/add_semester.html', {
        'title': 'Add semester',
        'form': form,
    })


@superuser_required
def import_offer_excel_view(request):
    summary = None
    error = None

    semesters = Semester.objects.all().order_by('name')

    selected_semester_id = (
        request.POST.get('semester')
        or request.GET.get('semester')
        or ''
    )

    if request.method == 'POST':

        uploaded_file = request.FILES.get('excel_file')

        if not selected_semester_id:
            error = 'Please select a semester before importing offers.'

        elif not uploaded_file:
            error = 'Please select an Excel file to upload.'

        else:
            try:
                semester = Semester.objects.get(
                    pk=selected_semester_id
                )

                summary = import_offer_excel(
                    uploaded_file,
                    semester=semester
                )

            except ValueError as exc:
                error = str(exc)

            except Semester.DoesNotExist:
                error = 'Selected semester does not exist.'

            except Exception as exc:
                error = f'Import failed: {exc}'

    return render(
        request,
        'offers/import_offer.html',
        {
            'title': 'Import offers',
            'summary': summary,
            'error': error,
            'semesters': semesters,
            'selected_semester_id': selected_semester_id,
        }
    )

def _offer_error(message, status=400):
    return JsonResponse({'ok': False, 'error': message}, status=status)


@superuser_required
@require_POST
def update_offer_roll_no(request, offer_id):
    offer = get_object_or_404(Offer, pk=offer_id)
    roll_no = request.POST.get('roll_no', '').strip()
    max_length = Offer._meta.get_field('roll_no').max_length
    if len(roll_no) > max_length:
        return _offer_error(f'Roll No. can be at most {max_length} characters.')
    if roll_no and Offer.objects.filter(roll_no__iexact=roll_no).exclude(pk=offer.pk).exists():
        return _offer_error(f'Roll No. {roll_no} is already assigned to another offer.')
    offer.roll_no = roll_no  # blank is allowed: roll_no is blank=True on the model
    offer.save(update_fields=['roll_no'])
    return JsonResponse({'ok': True, 'roll_no': offer.roll_no,
                         'message': f'Roll No. saved for {offer.student.application_no}.'})


@superuser_required
@require_POST
def remove_offer(request, offer_id):
    """Take a student off the offer list. The applicant record stays; only the offer is deleted."""
    offer = get_object_or_404(Offer.objects.select_related('student'), pk=offer_id)
    name, application_no = offer.student.full_name, offer.student.application_no
    offer.delete()
    messages.success(request, f'Offer removed for {name} ({application_no}). The applicant is still in All applicants.')
    next_url = request.POST.get('next', '')
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = reverse('home')
    return redirect(next_url)


@superuser_required
@require_POST
def update_offer_remarks(request, offer_id):
    offer = get_object_or_404(Offer, pk=offer_id)
    offer.remarks = request.POST.get('remarks', '').strip()
    offer.save(update_fields=['remarks'])
    return JsonResponse({'ok': True, 'remarks': offer.remarks,
                         'message': f'Remarks saved for {offer.student.application_no}.'})


@superuser_required
@require_POST
def update_offer_withdrawal(request, offer_id):
    offer = get_object_or_404(Offer, pk=offer_id)
    value = request.POST.get('withdrawn')
    if value not in ('true', 'false'):
        return _offer_error('Invalid withdrawal value.')
    offer.withdrawal_status = 'withdrawn' if value == 'true' else ''
    offer.save(update_fields=['withdrawal_status'])
    return JsonResponse({'ok': True, 'withdrawn': value == 'true',
                         'message': f'Withdrawal status updated for {offer.student.application_no}.'})


def _save_offer_date(request, offer_id, field, label):
    """Save one date field on one offer. A blank value clears the date."""
    offer = get_object_or_404(Offer, pk=offer_id)
    raw = request.POST.get(field, '').strip()
    if raw:
        try:
            value = date.fromisoformat(raw)  # the date picker sends YYYY-MM-DD
        except ValueError:
            return _offer_error(f'{label} must be a valid date.')
        if not 1990 <= value.year <= 2100:
            return _offer_error(f'{label} year must be between 1990 and 2100.')
    else:
        value = None
    setattr(offer, field, value)
    offer.save(update_fields=[field])
    return JsonResponse({
        'ok': True,
        field: value.isoformat() if value else '',
        'message': f'{label} saved for {offer.student.application_no}.',
    })


@superuser_required
@require_POST
def update_offer_fees_deadline(request, offer_id):
    return _save_offer_date(request, offer_id, 'fees_deadline', 'Fee deadline')


@superuser_required
@require_POST
def update_offer_date_of_joining(request, offer_id):
    return _save_offer_date(request, offer_id, 'date_of_joining', 'Date of joining')


@superuser_required
@require_POST
def update_offer_admission_category(request, offer_id):
    offer = get_object_or_404(Offer, pk=offer_id)
    value = ' '.join(request.POST.get('admission_offered_category', '').split())
    max_length = Offer._meta.get_field('admission_offered_category').max_length
    if len(value) > max_length:
        return _offer_error(f'Admission offered category can be at most {max_length} characters.')
    offer.admission_offered_category = value
    offer.save(update_fields=['admission_offered_category'])
    return JsonResponse({
        'ok': True,
        'admission_offered_category': offer.admission_offered_category,
        'message': f'Admission offered category saved for {offer.student.application_no}.',
    })


@superuser_required
@require_POST
def update_offer_iitgn_email(request, offer_id):
    offer = get_object_or_404(Offer.objects.select_related('student'), pk=offer_id)
    value = request.POST.get('iitgn_email_id', '').strip()
    if value:
        max_length = Student._meta.get_field('iitgn_email_id').max_length
        if len(value) > max_length:
            return _offer_error(f'IITGN email can be at most {max_length} characters.')
        try:
            validate_email(value)
        except ValidationError:
            return _offer_error('Enter a valid email address.')
    student = offer.student
    student.iitgn_email_id = value  # blank is allowed and clears the email
    student.save(update_fields=['iitgn_email_id'])
    return JsonResponse({
        'ok': True,
        'iitgn_email_id': student.iitgn_email_id,
        'message': f'IITGN email saved for {student.application_no}.',
    })