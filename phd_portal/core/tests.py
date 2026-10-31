import io
import re

import pandas as pd
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.shortcuts import resolve_url
from django.test import TestCase
from django.urls import reverse

from .fees_importer import import_fees_excel
from .importer import import_master_excel
from .models import Offer, Semester, Student, FacultyAccount
from .views import NOT_SET

def make_superuser(username='admin'):
    return get_user_model().objects.create_superuser(username, f'{username}@example.com', 'pw-admin-123')


def excel_bytes(frame):
    buf = io.BytesIO()
    frame.to_excel(buf, index=False)
    buf.seek(0)
    return buf


class OfferImportTests(TestCase):
    def setUp(self):
        self.semester = Semester.objects.create(name='Fall 2026')
        self.existing_student = Student.objects.create(
            application_no='APP-001',
            full_name='Existing Student',
            discipline='Computer Science',
            semester=self.semester,
        )
        self.new_student = Student.objects.create(
            application_no='APP-002',
            full_name='New Student',
            discipline='Computer Science',
            semester=self.semester,
        )
        self.existing_offer = Offer.create_for_student(self.existing_student, self.semester)

    def test_import_updates_existing_offers_and_creates_new_ones(self):
        self.client.force_login(make_superuser())
        uploaded_file = excel_bytes(pd.DataFrame({
            'Sr': [10, 11],
            'Appl. No.': ['APP-001', 'APP-002'],
        }))

        response = self.client.post(reverse('offer-import'), {
            'semester': str(self.semester.pk),
            'excel_file': SimpleUploadedFile(
                'offers.xlsx',
                uploaded_file.getvalue(),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            ),
        })

        self.existing_offer.refresh_from_db()
        new_offer = Offer.objects.get(student=self.new_student)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['summary'], {
            'created': 1,
            'updated': 1,
            'skipped': 0,
            'errors': [],
        })
        self.assertEqual(self.existing_offer.sr_no, '10')
        self.assertEqual(new_offer.sr_no, '11')
        self.assertEqual(new_offer.semester, self.semester)
        self.assertEqual(new_offer.dis_sr_no, 'Computer Science 2')


class AddStudentToOffersTests(TestCase):
    def setUp(self):
        self.client.force_login(make_superuser())
        self.active_semester = Semester.objects.create(name='Fall 2026', is_active=True)
        self.student = Student.objects.create(
            application_no='APP-001',
            full_name='Test Student',
            discipline='Computer Science',
        )

    def test_adds_student_to_active_semester(self):
        response = self.client.post(
            reverse('student-add-to-offers', args=[self.student.pk])
        )

        self.assertRedirects(response, reverse('student-list'))
        offer = Offer.objects.get(student=self.student)
        self.assertEqual(offer.semester, self.active_semester)
        self.assertEqual(offer.dis_sr_no, 'Computer Science 1')

    def test_rejects_student_who_already_has_offer(self):
        Offer.create_for_student(self.student)

        self.client.post(reverse('student-add-to-offers', args=[self.student.pk]))

        self.assertEqual(Offer.objects.filter(student=self.student).count(), 1)

    def test_rejects_when_no_active_semester(self):
        Semester.objects.update(is_active=False)

        self.client.post(reverse('student-add-to-offers', args=[self.student.pk]))

        self.assertFalse(Offer.objects.exists())

    def test_get_does_not_create_offer(self):
        self.client.get(reverse('student-add-to-offers', args=[self.student.pk]))

        self.assertFalse(Offer.objects.exists())

    def test_external_next_url_is_ignored(self):
        response = self.client.post(
            reverse('student-add-to-offers', args=[self.student.pk]),
            {'next': 'https://evil.example.com/'},
        )

        self.assertRedirects(response, reverse('student-list'))

    def test_serial_numbers_increment_within_discipline(self):
        other = Student.objects.create(
            application_no='APP-002', full_name='Other', discipline='Computer Science'
        )
        Offer.create_for_student(self.student)
        offer = Offer.create_for_student(other)

        self.assertEqual(offer.dis_sr_no, 'Computer Science 2')

    def test_non_superuser_is_forbidden(self):
        self.client.force_login(get_user_model().objects.create_user('plain', password='x'))

        response = self.client.post(reverse('student-add-to-offers', args=[self.student.pk]))

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Offer.objects.exists())


class DashboardOfferFilterTests(TestCase):
    def setUp(self):
        self.client.force_login(make_superuser())
        self.active_semester = Semester.objects.create(name='Fall 2026', is_active=True)
        self.previous_semester = Semester.objects.create(name='Spring 2026')
        self.active_student = Student.objects.create(
            application_no='ACTIVE-001', full_name='Active Student', discipline='Physics'
        )
        self.previous_student = Student.objects.create(
            application_no='PREVIOUS-001', full_name='Previous Student', discipline='Physics'
        )
        Offer.objects.create(
            student=self.active_student,
            semester=self.active_semester,
            dis_sr_no='Physics 1',
            fees_paid=True,
        )
        Offer.objects.create(
            student=self.previous_student,
            semester=self.previous_semester,
            dis_sr_no='Physics 1',
        )

    def test_defaults_to_active_semester_offers(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.context['total_offers'], 1)
        self.assertEqual(response.context['paid_offers'], 1)
        self.assertEqual(response.context['unpaid_offers'], 0)
        self.assertEqual(list(response.context['offers']), [self.active_student.offer])

    def test_can_view_another_semesters_offers(self):
        response = self.client.get(
            reverse('home'), {'semester': self.previous_semester.pk}
        )

        self.assertEqual(response.context['total_offers'], 1)
        self.assertEqual(response.context['paid_offers'], 0)
        self.assertEqual(list(response.context['offers']), [self.previous_student.offer])

    def test_all_semesters_shows_every_offer(self):
        response = self.client.get(reverse('home'), {'semester': 'all'})

        self.assertEqual(response.context['total_offers'], 2)
        self.assertEqual(response.context['paid_offers'], 1)
        self.assertEqual(response.context['unpaid_offers'], 1)

    def test_unknown_semester_falls_back_to_active(self):
        response = self.client.get(reverse('home'), {'semester': 9999})

        self.assertEqual(response.context['selected_semester'], self.active_semester)

    def test_anonymous_is_sent_to_login(self):
        self.client.logout()

        self.assertRedirects(self.client.get(reverse('home')), f"{reverse('login')}?next={reverse('home')}")

    def test_non_superuser_is_forbidden(self):
        self.client.force_login(get_user_model().objects.create_user('plain', password='x'))

        self.assertEqual(self.client.get(reverse('home')).status_code, 403)


class MasterDataTests(TestCase):
    def setUp(self):
        self.client.force_login(make_superuser())
        self.semester = Semester.objects.create(name='Autumn 2026', is_active=True)
        self.alice = Student.objects.create(
            application_no='A1', full_name='Alice Rao', semester=self.semester, discipline='Physics'
        )
        self.bob = Student.objects.create(
            application_no='B2', full_name='Bob Shah', semester=self.semester, discipline='Chemistry'
        )

    def students(self, **params):
        return list(self.client.get(reverse('student-list'), params).context['students'])

    def test_search_by_name_and_application_no(self):
        self.assertEqual(self.students(q='alice'), [self.alice])
        self.assertEqual(self.students(q='B2'), [self.bob])

    def test_search_by_discipline(self):
        self.assertEqual(self.students(q='chem'), [self.bob])

    def test_search_with_no_match_is_empty(self):
        response = self.client.get(reverse('student-list'), {'q': 'nobody'})

        self.assertEqual(response.context['result_count'], 0)

    def test_add_to_offers_shows_on_dashboard(self):
        self.client.post(reverse('student-add-to-offers', args=[self.alice.pk]))

        self.assertEqual([o.student for o in self.client.get(reverse('home')).context['offers']], [self.alice])
        self.assertEqual(self.students(offer='not_offered'), [self.bob])
        self.assertEqual(self.students(offer='offered'), [self.alice])

    def test_semester_filter_limits_students(self):
        other = Semester.objects.create(name='Spring 2027')
        carol = Student.objects.create(application_no='C3', full_name='Carol', semester=other)

        self.assertEqual(self.students(), [self.alice, self.bob])  # defaults to active semester
        self.assertEqual(self.students(semester=other.pk), [carol])
        self.assertEqual(len(self.students(semester='all')), 3)

    def test_master_data_renders_all_student_columns(self):
        response = self.client.get(reverse('student-list'))

        for heading in (
            'Sr. No.', 'Application No', 'First Name', 'Middle Name', 'Last Name',
            'Full Name', 'Semester', 'Program',
            'Discipline', 'Research Area', 'Category', 'Date of Birth',
            'Gender', 'Contact No 1', 'Contact No 2', 'Email',
            'Permanent Address 1', 'Permanent Address 2', 'City', 'PIN Code',
            'State', 'IITGN Email ID',
        ):
            self.assertContains(response, heading)
        self.assertNotContains(response, 'Application Status')
        self.assertNotContains(response, 'Sub-programme')

    def test_master_data_uses_row_serial_number(self):
        self.semester.students.create(id=90, application_no='Z3', full_name='Zoe')

        response = self.client.get(reverse('student-list'))

        self.assertContains(response, '<td>3</td>', html=False)
        self.assertNotContains(response, '<td>90</td>', html=False)

    def test_master_data_filters_compose(self):
        self.semester.students.create(
            application_no='A2',
            full_name='Alice Peng',
            program='M.Tech',
            discipline='Physics',
            category='Regular',
        )
        self.semester.students.create(
            application_no='A3',
            full_name='Alice Smith',
            program='M.Tech',
            discipline='Chemistry',
            category='Regular',
        )

        response = self.client.get(reverse('student-list'), {
            'program': ['M.Tech'],
            'discipline': ['Physics'],
            'category': ['Regular'],
        })

        self.assertEqual([student.application_no for student in response.context['students']], ['A2'])
        self.assertEqual(response.context['program_filter'], ['M.Tech'])
        self.assertEqual(response.context['discipline_filter'], ['Physics'])
        self.assertEqual(response.context['category_filter'], ['Regular'])

    def test_multiple_programs_disciplines_and_categories_can_be_selected(self):
        self.semester.students.create(
            application_no='A2', full_name='Alice Peng', program='M.Tech', discipline='Physics', category='Regular'
        )
        self.semester.students.create(
            application_no='A3', full_name='Alice Smith', program='B.Tech', discipline='Chemistry', category='Regular'
        )
        self.semester.students.create(
            application_no='A4', full_name='Alice Lee', program='M.Tech', discipline='Chemistry', category='External'
        )

        response = self.client.get(reverse('student-list'), {
            'program': ['M.Tech', 'B.Tech'],
            'discipline': ['Physics', 'Chemistry'],
            'category': ['Regular', 'External'],
        })

        self.assertEqual(
            {student.application_no for student in response.context['students']},
            {'A2', 'A3', 'A4'},
        )


class StudentEditDeleteTests(TestCase):
    def setUp(self):
        self.client.force_login(make_superuser())
        self.semester = Semester.objects.create(name='Fall 2026', is_active=True)
        self.student = Student.objects.create(
            application_no='E-1', full_name='Old Name', semester=self.semester, discipline='Physics'
        )

    def test_edit_updates_student(self):
        response = self.client.post(
            reverse('student-edit', args=[self.student.pk]),
            {'full_name': 'New Name', 'discipline': 'Chemistry', 'email': 'new@example.com'},
        )

        self.assertRedirects(response, reverse('student-list'))
        self.student.refresh_from_db()
        self.assertEqual(self.student.full_name, 'New Name')
        self.assertEqual(self.student.discipline, 'Chemistry')
        self.assertEqual(self.student.application_no, 'E-1')  # not editable

    def test_edit_rejects_blank_name(self):
        response = self.client.post(reverse('student-edit', args=[self.student.pk]), {'full_name': ''})

        self.assertEqual(response.status_code, 200)
        self.assertIn('full_name', response.context['form'].errors)
        self.student.refresh_from_db()
        self.assertEqual(self.student.full_name, 'Old Name')

    def test_edit_rejects_invalid_email(self):
        response = self.client.post(
            reverse('student-edit', args=[self.student.pk]),
            {'full_name': 'Old Name', 'email': 'not-an-email'},
        )

        self.assertIn('email', response.context['form'].errors)

    def test_edit_unknown_student_is_404(self):
        self.assertEqual(self.client.get(reverse('student-edit', args=[9999])).status_code, 404)

    def test_delete_removes_student_and_offer(self):
        Offer.create_for_student(self.student)

        response = self.client.post(reverse('student-delete', args=[self.student.pk]))

        self.assertRedirects(response, reverse('student-list'))
        self.assertFalse(Student.objects.filter(pk=self.student.pk).exists())
        self.assertFalse(Offer.objects.exists())

    def test_delete_requires_post(self):
        response = self.client.get(reverse('student-delete', args=[self.student.pk]))

        self.assertRedirects(response, reverse('student-list'))
        self.assertTrue(Student.objects.filter(pk=self.student.pk).exists())

    def test_delete_unknown_student_redirects(self):
        response = self.client.post(reverse('student-delete', args=[9999]))

        self.assertRedirects(response, reverse('student-list'))

    def test_non_superuser_cannot_edit_or_delete(self):
        self.client.force_login(get_user_model().objects.create_user('plain', password='x'))

        self.assertEqual(self.client.post(reverse('student-delete', args=[self.student.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse('student-edit', args=[self.student.pk])).status_code, 403)
        self.assertTrue(Student.objects.filter(pk=self.student.pk).exists())


class SemesterToggleTests(TestCase):
    def setUp(self):
        self.client.force_login(make_superuser())

    def toggle(self, semester):
        return self.client.post(reverse('semester-toggle-active', args=[semester.pk]))

    def test_toggle_active(self):
        a = Semester.objects.create(name='A', is_active=True)
        b = Semester.objects.create(name='B')
        self.toggle(a)
        a.refresh_from_db()
        self.assertFalse(a.is_active)
        self.toggle(a)
        self.toggle(b)
        a.refresh_from_db(); b.refresh_from_db()
        self.assertEqual((a.is_active, b.is_active), (False, True))

    def test_get_does_not_toggle(self):
        a = Semester.objects.create(name='A', is_active=True)

        self.client.get(reverse('semester-toggle-active', args=[a.pk]))

        a.refresh_from_db()
        self.assertTrue(a.is_active)

    def test_unknown_semester_redirects(self):
        response = self.client.post(reverse('semester-toggle-active', args=[9999]))

        self.assertRedirects(response, reverse('semester-list'))


class SemesterManagementTests(TestCase):
    def setUp(self):
        self.client.force_login(make_superuser())

    def test_add_semester(self):
        response = self.client.post(reverse('semester-add'), {'name': '2026-27 Semester 1'})

        self.assertRedirects(response, reverse('semester-list'))
        self.assertTrue(Semester.objects.filter(name='2026-27 Semester 1').exists())

    def test_duplicate_name_is_rejected(self):
        Semester.objects.create(name='Dup')

        response = self.client.post(reverse('semester-add'), {'name': 'Dup'})

        self.assertIn('name', response.context['form'].errors)
        self.assertEqual(Semester.objects.count(), 1)

    def test_second_active_semester_is_rejected(self):
        Semester.objects.create(name='Current', is_active=True)

        response = self.client.post(reverse('semester-add'), {'name': 'Next', 'is_active': 'on'})

        self.assertIn('is_active', response.context['form'].errors)
        self.assertFalse(Semester.objects.filter(name='Next').exists())

    def test_semester_list_shows_semesters(self):
        Semester.objects.create(name='Visible Sem')

        self.assertContains(self.client.get(reverse('semester-list')), 'Visible Sem')


class OfferModelTests(TestCase):
    def setUp(self):
        self.semester = Semester.objects.create(name='Fall 2026', is_active=True)

    def test_blank_discipline_uses_general(self):
        student = Student.objects.create(application_no='G-1', full_name='Gen')

        self.assertEqual(Offer.create_for_student(student).dis_sr_no, 'General 1')

    def test_hyphenated_discipline_uses_last_part(self):
        student = Student.objects.create(application_no='H-1', full_name='Hy', discipline='School - Physics')

        self.assertEqual(Offer.create_for_student(student).dis_sr_no, 'Physics 1')

    def test_numbering_is_per_semester(self):
        other = Semester.objects.create(name='Spring 2027')
        first = Student.objects.create(application_no='N-1', full_name='One', discipline='Physics')
        second = Student.objects.create(application_no='N-2', full_name='Two', discipline='Physics')

        Offer.create_for_student(first, self.semester)

        self.assertEqual(Offer.create_for_student(second, other).dis_sr_no, 'Physics 1')

    def test_uses_students_own_semester(self):
        other = Semester.objects.create(name='Spring 2027')
        student = Student.objects.create(application_no='S-1', full_name='Sem', semester=other)

        self.assertEqual(Offer.create_for_student(student).semester, other)

    def test_duplicate_offer_raises(self):
        student = Student.objects.create(application_no='D-1', full_name='Dup')
        Offer.create_for_student(student)

        with self.assertRaises(ValueError):
            Offer.create_for_student(student)

    def test_invalid_withdrawal_status_fails_validation(self):
        student = Student.objects.create(application_no='W-1', full_name='Wd')
        offer = Offer(student=student, semester=self.semester, dis_sr_no='X 1', withdrawal_status='maybe')

        with self.assertRaises(ValidationError):
            offer.full_clean()

    def test_student_requires_name_and_application_no(self):
        with self.assertRaises(ValidationError):
            Student(application_no='  ', full_name='Name').full_clean()
        with self.assertRaises(ValidationError):
            Student(application_no='Z-1', full_name='  ').full_clean()


class StudentImportTests(TestCase):
    COLUMNS = [
        'Application No', 'Program', 'Discipline', 'First Name', 'Middle Name', 'Last Name',
        'Application Status', 'Category', 'Dob', 'Gender', 'Preaddress1', 'Preaddress2',
        'Precity', 'Prepincode', 'Prestate', 'Prephone', 'Premobile', 'Email',
        'Peraddress1', 'Peraddress2', 'Percity', 'Perpincode', 'Perstate',
    ]

    def setUp(self):
        self.semester = Semester.objects.create(name='Fall 2026', is_active=True)

    def frame(self, rows):
        return pd.DataFrame([{**{c: '' for c in self.COLUMNS}, **row} for row in rows])

    def test_imports_valid_rows(self):
        data = excel_bytes(self.frame([
            {'Application No': 'I-1', 'First Name': 'Asha', 'Middle Name': 'K', 'Last Name': 'Rao',
             'Discipline': 'Physics', 'Email': 'asha@example.com', 'Peraddress1': '1 Main St'},
        ]))

        summary = import_master_excel(data, semester=self.semester)

        self.assertEqual(summary['imported'], 1)
        student = Student.objects.get(application_no='I-1')
        self.assertEqual(student.full_name, 'Asha K Rao')
        self.assertEqual(student.semester, self.semester)
        self.assertEqual(student.permanent_address_line_1, '1 Main St')

    def test_imports_full_supplied_schema_using_existing_fields_only(self):
        wide_columns = [
            'Sr#', 'Application No', 'Date Of Application', 'Program', 'Discipline', 'Phase',
            'Research Area', 'First Name', 'Middle Name', 'Last Name', 'Application Status',
            'Applicable Fees', 'Fees Paid', 'Payment Date', 'Fees Status', 'Dob', 'Gender',
            'Marital', 'Nationality', 'Category', 'Preaddress1', 'Preaddress2', 'Precity',
            'Prepincode', 'Prestate', 'Precountry', 'Prephone', 'Premobile',
            'Guardian Contact No', 'Guardian Name', 'Email', 'Altemail', 'Gmail ID',
            'Peraddress1', 'Peraddress2', 'Percity', 'Perpincode', 'Perstate', 'Percountry',
            'GATEdiscipline', 'GATEYear', 'GATEmarks', 'GATEscore', 'GATErank', 'GATEregno',
            'GATEpercentage', 'GATEcandidates', 'NLexamname1', 'NLexamyear1', 'NLexammarks1',
            'NLexamscore1', 'NLexamrank1', 'NLexamdiscipline1', 'NLexamregno1',
            'NLexampercentage1', 'NLexamcandidates1', 'Percentile', 'Extra Field',
        ]
        row = {
            'Application No': 'WIDE-001',
            'Program': 'PhD', 'Discipline': 'Computer Science', 'Phase': 'Regular',
            'Research Area': 'Distributed systems',
            'First Name': 'Asha', 'Middle Name': 'K', 'Last Name': 'Rao',
            'Application Status': 'Accepted', 'Category': 'Regular', 'Dob': '2000-01-01',
            'Gender': 'Female', 'Prephone': '1234567890', 'Premobile': '9876543210',
            'Email': 'asha@example.com', 'Gmail ID': 'asha@gmail.com',
            'Peraddress1': '1 Main St', 'Peraddress2': 'Apartment 2',
            'Percity': 'Bengaluru', 'Perpincode': '560001', 'Perstate': 'Karnataka',
            'Extra Field': 'must-not-be-persisted',
        }
        data = excel_bytes(pd.DataFrame([{**{column: '' for column in wide_columns}, **row}]))

        summary = import_master_excel(data, semester=self.semester)

        self.assertEqual(summary['imported'], 1)
        student = Student.objects.get(application_no='WIDE-001')
        self.assertEqual(student.full_name, 'Asha K Rao')
        self.assertEqual(student.first_name, 'Asha')
        self.assertEqual(student.middle_name, 'K')
        self.assertEqual(student.last_name, 'Rao')
        self.assertEqual(student.research_area, 'Distributed systems')
        self.assertEqual(student.status_of_application, 'Accepted')
        self.assertEqual(student.contact_no_1, '1234567890')
        self.assertEqual(student.contact_no_2, '9876543210')
        self.assertEqual(student.permanent_address_line_1, '1 Main St')
        self.assertEqual(student.address_line_2, 'Apartment 2')
        self.assertEqual(student.iitgn_email_id, 'asha@gmail.com')

    def test_defaults_to_active_semester(self):
        data = excel_bytes(self.frame([{'Application No': 'I-1', 'First Name': 'Asha'}]))

        import_master_excel(data)

        self.assertEqual(Student.objects.get().semester, self.semester)

    def test_skips_existing_and_counts_invalid_rows(self):
        Student.objects.create(application_no='I-1', full_name='Existing', semester=self.semester)
        data = excel_bytes(self.frame([
            {'Application No': 'I-1', 'First Name': 'Dup'},
            {'Application No': '', 'First Name': 'No App'},
            {'Application No': 'I-2', 'First Name': ''},
            {'Application No': 'I-3', 'First Name': 'Good'},
        ]))

        summary = import_master_excel(data, semester=self.semester)

        self.assertEqual(summary['total_rows'], 4)
        self.assertEqual(summary['skipped_existing'], 1)
        self.assertEqual(summary['invalid_rows'], 2)
        self.assertEqual(summary['imported'], 1)
        self.assertEqual(Student.objects.get(application_no='I-1').full_name, 'Existing')

    def test_attaches_semesterless_student(self):
        Student.objects.create(application_no='I-1', full_name='Old')
        data = excel_bytes(self.frame([{'Application No': 'I-1', 'First Name': 'Old'}]))

        summary = import_master_excel(data, semester=self.semester)

        self.assertEqual(summary['imported'], 1)
        self.assertEqual(Student.objects.get().semester, self.semester)

    def test_import_updates_research_area_for_existing_student(self):
        student = Student.objects.create(
            application_no='I-1', full_name='Existing', semester=self.semester
        )
        data = excel_bytes(self.frame([
            {'Application No': 'I-1', 'Research Area': 'Machine learning'},
        ]))

        summary = import_master_excel(data, semester=self.semester)

        self.assertEqual(summary['skipped_existing'], 1)
        student.refresh_from_db()
        self.assertEqual(student.research_area, 'Machine learning')

    def test_import_updates_name_parts_for_existing_student(self):
        student = Student.objects.create(
            application_no='I-1', full_name='Existing Name', semester=self.semester
        )
        data = excel_bytes(self.frame([
            {
                'Application No': 'I-1',
                'First Name': 'Asha',
                'Middle Name': 'K',
                'Last Name': 'Rao',
            },
        ]))

        import_master_excel(data, semester=self.semester)

        student.refresh_from_db()
        self.assertEqual(student.first_name, 'Asha')
        self.assertEqual(student.middle_name, 'K')
        self.assertEqual(student.last_name, 'Rao')
        self.assertEqual(student.full_name, 'Asha K Rao')

    def test_import_accepts_long_research_area(self):
        research_area = 'Research topic ' * 40
        data = excel_bytes(self.frame([
            {
                'Application No': 'LONG-1',
                'First Name': 'Asha',
                'Research Area': research_area,
            },
        ]))

        summary = import_master_excel(data, semester=self.semester)

        self.assertEqual(summary['imported'], 1)
        self.assertEqual(
            Student.objects.get(application_no='LONG-1').research_area,
            research_area.strip(),
        )

    def test_missing_columns_raises(self):
        data = excel_bytes(pd.DataFrame({'Application No': ['I-1']}))

        with self.assertRaisesMessage(ValueError, 'Missing required Excel columns'):
            import_master_excel(data, semester=self.semester)

    def test_requires_a_semester(self):
        Semester.objects.update(is_active=False)
        data = excel_bytes(self.frame([{'Application No': 'I-1', 'First Name': 'A'}]))

        with self.assertRaises(ValueError):
            import_master_excel(data)

    def test_view_requires_semester_and_file(self):
        self.client.force_login(make_superuser())
        url = reverse('student-import')

        response = self.client.post(url, {})
        self.assertIn('select a semester', response.context['error'])

        response = self.client.post(url, {'semester': self.semester.pk})
        self.assertIn('select an Excel file', response.context['error'])

    def test_view_imports_uploaded_file(self):
        self.client.force_login(make_superuser())
        upload = SimpleUploadedFile(
            'students.xlsx',
            excel_bytes(self.frame([{'Application No': 'I-1', 'First Name': 'Asha'}])).read(),
        )

        response = self.client.post(
            reverse('student-import'), {'semester': self.semester.pk, 'excel_file': upload}
        )

        self.assertEqual(response.context['summary']['imported'], 1)
        self.assertTrue(Student.objects.filter(application_no='I-1').exists())

    def test_view_reports_bad_file(self):
        self.client.force_login(make_superuser())
        upload = SimpleUploadedFile('bad.xlsx', b'not an excel file')

        response = self.client.post(
            reverse('student-import'), {'semester': self.semester.pk, 'excel_file': upload}
        )

        self.assertTrue(response.context['error'])
        self.assertIsNone(response.context['summary'])
        self.assertFalse(Student.objects.exists())


class FeesImportTests(TestCase):
    def test_fees_matching(self):
        sem = Semester.objects.create(name='S', is_active=True)
        a = Student.objects.create(application_no='261CDP100189', full_name='Abhishek Anand', semester=sem)
        b = Student.objects.create(application_no='X2', full_name='Pragya Singh', semester=sem, email='psingh@x.com')
        c = Student.objects.create(application_no='X3', full_name='Not Paid', semester=sem)
        for s in (a, b, c):
            Offer.create_for_student(s)
        buf = excel_bytes(pd.DataFrame({
            'Sr. No.': [1, 2, 3, 4, 5],
            'Roll No Application No': ['261CDP100189', 'ZZZ', '261CDP100189', 'NOPE', 'NOPE2'],
            'Amount': [100, 64496, 50, 10, 10],
            'STATUS': ['TXN_SUCCESS', 'TXN_SUCCESS', 'TXN_SUCCESS', 'TXN_SUCCESS', 'TXN_FAILURE'],
            'Name': ['Abhishek Anand', 'pragya  singh', 'Abhishek Anand', 'Stranger', 'Stranger'],
            'Email': ['', '', '', '', ''],
        }))
        summary = import_fees_excel(buf)
        self.assertEqual(summary['updated'], 2)
        self.assertEqual(summary['not_successful'], 1)
        self.assertEqual(len(summary['unmatched']), 1)
        self.assertEqual(summary['by_name'], 1)
        a.offer.refresh_from_db(); b.offer.refresh_from_db(); c.offer.refresh_from_db()
        self.assertEqual((a.offer.fees_paid, a.offer.fees_amount), (True, 150))
        self.assertEqual((b.offer.fees_paid, b.offer.fees_amount), (True, 64496))
        self.assertFalse(c.offer.fees_paid)
        # No dates or order ids in this file, so the first row wins.
        self.assertEqual(a.offer.first_fees_amount, 100)
        self.assertIsNone(c.offer.first_fees_amount)

    def _gateway_file(self, rows):
        return excel_bytes(pd.DataFrame(rows, columns=[
            'Order ID', 'Roll No Application No', 'Date and Time', 'Amount', 'STATUS', 'Name', 'Email',
        ]))

    def test_first_amount_is_earliest_payment_not_first_row(self):
        sem = Semester.objects.create(name='S', is_active=True)
        student = Student.objects.create(application_no='23110285', full_name='Saankho Bardhan', semester=sem)
        Offer.create_for_student(student)
        # Gateway exports list newest first, so the earliest payment is the last row.
        summary = import_fees_excel(self._gateway_file([
            ['LWALLET26063404', 23110285, '2026-06-29 13:56:27', 2110, 'TXN_SUCCESS', 'Saankho Bardhan', ''],
            ['LWALLET26063390', 23110285, '2026-06-29 10:30:00', 999, 'TXN_FAILURE', 'Saankho Bardhan', ''],
            ['LWALLET26063376', 23110285, '2026-06-29 10:08:36', 152750, 'TXN_SUCCESS', 'Saankho Bardhan', ''],
        ]))
        offer = Offer.objects.get(student=student)
        self.assertEqual(summary['updated'], 1)
        self.assertTrue(offer.fees_paid)
        self.assertEqual(offer.fees_amount, 154860)
        self.assertEqual(offer.first_fees_amount, 152750)
        self.assertEqual(offer.first_fees_paid_on.isoformat(), '2026-06-29T04:38:36+00:00')  # 10:08:36 IST

    def test_header_punctuation_variants_are_recognised(self):
        sem = Semester.objects.create(name='S', is_active=True)
        student = Student.objects.create(application_no='23310068', full_name='Bhavani J', semester=sem)
        Offer.create_for_student(student)
        import_fees_excel(excel_bytes(pd.DataFrame({
            'Roll No/Application No': [23310068],
            'Date & Time': ['2026-07-31 10:00:00'],
            'Amount': [20000],
            'Status': ['TXN_SUCCESS'],
        })))
        offer = Offer.objects.get(student=student)
        self.assertTrue(offer.fees_paid)
        self.assertEqual(offer.first_fees_amount, 20000)
        self.assertIsNotNone(offer.first_fees_paid_on)

    def test_order_id_breaks_ties_on_equal_times(self):
        sem = Semester.objects.create(name='S', is_active=True)
        student = Student.objects.create(application_no='23310068', full_name='Bhavani J', semester=sem)
        Offer.create_for_student(student)
        import_fees_excel(self._gateway_file([
            ['LWALLET26073902', '23310068', '2026-07-31 11:00:00', 35360, 'TXN_SUCCESS', 'Bhavani J', ''],
            ['LWALLET26073901', '23310068', '2026-07-31 11:00:00', 20000, 'TXN_SUCCESS', 'Bhavani J', ''],
        ]))
        self.assertEqual(Offer.objects.get(student=student).first_fees_amount, 20000)

    def test_later_import_keeps_original_first_payment(self):
        sem = Semester.objects.create(name='S', is_active=True)
        student = Student.objects.create(application_no='23310068', full_name='Bhavani J', semester=sem)
        Offer.create_for_student(student)
        import_fees_excel(self._gateway_file([
            ['LWALLET1', '23310068', '2026-07-01 09:00:00', 20000, 'TXN_SUCCESS', 'Bhavani J', ''],
        ]))
        import_fees_excel(self._gateway_file([
            ['LWALLET2', '23310068', '2026-07-31 09:00:00', 35360, 'TXN_SUCCESS', 'Bhavani J', ''],
        ]))
        offer = Offer.objects.get(student=student)
        self.assertEqual(offer.first_fees_amount, 20000)
        # An even earlier payment found later does replace it.
        import_fees_excel(self._gateway_file([
            ['LWALLET0', '23310068', '2026-06-15 09:00:00', 5000, 'TXN_SUCCESS', 'Bhavani J', ''],
        ]))
        offer.refresh_from_db()
        self.assertEqual(offer.first_fees_amount, 5000)

    def test_dashboard_shows_first_amount_paid(self):
        sem = Semester.objects.create(name='S', is_active=True)
        student = Student.objects.create(application_no='23310068', full_name='Bhavani J', semester=sem)
        Offer.create_for_student(student)
        Student.objects.create(application_no='X9', full_name='Not Paid', semester=sem)
        Offer.create_for_student(Student.objects.get(application_no='X9'))
        import_fees_excel(self._gateway_file([
            ['LWALLET1', '23310068', '2026-07-31 10:00:00', 20000, 'TXN_SUCCESS', 'Bhavani J', ''],
        ]))
        self.client.force_login(make_superuser())
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'First Amount Paid')
        self.assertContains(response, '&#8377;20,000')
        self.assertContains(response, '31 Jul 2026, 10:00')

class LiveSheetTests(TestCase):
	"""The faculty account and superusers see every branch, grouped branch-wise."""

	def setUp(self):
		User = get_user_model()
		self.faculty = User.objects.create_user('faculty', password='pw-12345-x')
		FacultyAccount.objects.create(pk=1, user=self.faculty)
		self.outsider = User.objects.create_user('outsider', password='pw-12345-x')
		self.superuser = User.objects.create_superuser('admin', 'a@example.com', 'pw-admin-123')
		self.semester = Semester.objects.create(name='Fall 2026', is_active=True)
		self.url = reverse('live-sheet')
		self._offer('AI-1', 'AI', 'Ann')
		self._offer('AI-2', 'AI', 'Bob', sub='Direct', category='OBC')
		self._offer('AI-3', 'AI', 'Cat', program='M.Tech-Research', sub='')
		self._offer('CS-1', 'CS', 'Dan')
		self._offer('CS-2', 'CS', 'Eve', sub='Direct')
		self.client.force_login(self.faculty)

	def _offer(self, app_no, discipline, name, semester=None, program='Ph.D.-Regular', sub='Regular', category='GEN'):
		student = Student.objects.create(
			application_no=app_no, full_name=name, discipline=discipline, program=program,
			sub_programme=sub, category=category,
		)
		Offer.create_for_student(student, semester or self.semester)

	def _names(self, response):
		return {o.student.full_name for g in response.context['groups'] for o in g['offers']}

	def test_faculty_account_sees_all_branches(self):
		response = self.client.get(self.url)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(self._names(response), {'Ann', 'Bob', 'Cat', 'Dan', 'Eve'})

	def test_superuser_sees_the_same_sheet(self):
		self.client.force_login(self.superuser)

		self.assertEqual(self._names(self.client.get(self.url)), {'Ann', 'Bob', 'Cat', 'Dan', 'Eve'})

	def test_grouped_branch_wise(self):
		groups = self.client.get(self.url).context['groups']

		self.assertEqual([g['branch'] for g in groups], ['AI', 'CS'])
		self.assertEqual([g['count'] for g in groups], [3, 2])

	def test_live_sheet_uses_simple_sequential_serial_numbers(self):
		response = self.client.get(self.url)
		serial_numbers = [
			offer.live_sheet_sr_no
			for group in response.context['groups']
			for offer in group['offers']
		]

		self.assertEqual(serial_numbers, [1, 2, 3, 4, 5])
		self.assertContains(response, '<th>Sr. No.</th>', html=True)

	def test_filters_default_to_all(self):
		response = self.client.get(self.url)

		for name in ('program', 'sub_programme', 'branch'):
			self.assertEqual(response.context[f'selected_{name}'], '')
		html = response.content.decode()
		self.assertIn('All programmes', html)
		self.assertIn('All sub-programmes', html)
		self.assertIn('All branches', html)
		self.assertNotIn('Supervisor', html)

	def test_branch_filter_label_is_discipline(self):
		response = self.client.get(self.url)

		self.assertEqual(response.context['filter_fields'][2]['label'], 'Discipline')

	def test_branch_filter(self):
		response = self.client.get(self.url, {'branch': 'CS'})

		self.assertEqual(self._names(response), {'Dan', 'Eve'})
		self.assertEqual([g['branch'] for g in response.context['groups']], ['CS'])

	def test_programme_filter(self):
		response = self.client.get(self.url, {'program': 'M.Tech-Research'})

		self.assertEqual(self._names(response), {'Cat'})

	def test_sub_programme_filter(self):
		response = self.client.get(self.url, {'sub_programme': 'Direct'})

		self.assertEqual(self._names(response), {'Bob', 'Eve'})

	def test_blank_sub_programme_can_be_filtered(self):
		response = self.client.get(self.url, {'sub_programme': NOT_SET})

		self.assertEqual(self._names(response), {'Cat'})
		self.assertIn((NOT_SET, 'Not specified'), response.context['sub_programme_options'])

	def test_filters_combine(self):
		response = self.client.get(self.url, {'branch': 'CS', 'sub_programme': 'Direct'})
		self.assertEqual(self._names(response), {'Eve'})

		response = self.client.get(self.url, {'branch': 'CS', 'program': 'M.Tech-Research'})
		self.assertEqual(self._names(response), set())
		self.assertContains(response, 'No offers found.')

	def test_unknown_filter_value_falls_back_to_all(self):
		response = self.client.get(self.url, {'branch': 'Astrology', 'program': 'Nope', 'sub_programme': 'Nope'})

		self.assertEqual(response.context['selected_branch'], '')
		self.assertEqual(response.context['selected_program'], '')
		self.assertEqual(response.context['selected_sub_programme'], '')
		self.assertEqual(len(self._names(response)), 5)

	def test_dropdowns_list_every_option(self):
		response = self.client.get(self.url)

		self.assertEqual([v for v, _ in response.context['branch_options']], ['AI', 'CS'])
		self.assertEqual([v for v, _ in response.context['program_options']], ['M.Tech-Research', 'Ph.D.-Regular'])
		self.assertEqual([l for _, l in response.context['sub_programme_options']], ['Direct', 'Regular', 'Not specified'])

	def test_semester_filter_narrows_the_dropdowns_too(self):
		other = Semester.objects.create(name='Spring 2027')
		self._offer('ME-1', 'ME', 'Gus', semester=other)

		response = self.client.get(self.url, {'semester': self.semester.pk})

		self.assertNotIn('ME', [v for v, _ in response.context['branch_options']])
		self.assertEqual(self._names(response), {'Ann', 'Bob', 'Cat', 'Dan', 'Eve'})

	def test_rows_follow_dis_sr_order_inside_a_branch(self):
		for i in range(2, 11):
			self._offer(f'AI-X{i}', 'AI', f'Person{i}')

		ai = self.client.get(self.url).context['groups'][0]
		numbers = [int(o.dis_sr_no.rsplit(' ', 1)[1]) for o in ai['offers']]
		self.assertEqual(numbers, sorted(numbers))

	def test_page_shows_the_requested_columns(self):
		response = self.client.get(self.url)
		html = response.content.decode()

		self.assertEqual(re.findall(r'<th>(.*?)</th>', html)[:9], [
			'Application No', 'Status of Fees Payment', 'Program', 'Sub programme', 'Discipline',
			'Name of Candidate', 'Category', 'Withdrawal Status', 'Remarks',
		])
		self.assertContains(response, 'OBC')

	def test_anonymous_visitor_is_sent_to_login(self):
		self.client.logout()
		response = self.client.get(self.url)

		self.assertEqual(response.status_code, 302)
		self.assertTrue(response['Location'].startswith(resolve_url(settings.LOGIN_URL)))

	def test_faculty_login_lands_on_live_sheet_and_superuser_on_dashboard(self):
		self.client.logout()
		response = self.client.post(reverse('login'), {'username': 'faculty', 'password': 'pw-12345-x'})
		self.assertRedirects(response, self.url, fetch_redirect_response=False)
		self.client.logout()
		response = self.client.post(reverse('login'), {'username': 'admin', 'password': 'pw-admin-123'})
		self.assertRedirects(response, reverse('home'), fetch_redirect_response=False)

	def test_other_logged_in_users_cannot_open_the_live_sheet(self):
		self.client.force_login(self.outsider)

		self.assertEqual(self.client.get(self.url).status_code, 403)

	def test_nav_for_faculty_shows_only_the_live_sheet_and_for_superuser_the_account_page(self):
		faculty_html = self.client.get(self.url).content.decode()
		self.assertIn('Faculty Live Sheet', faculty_html)
		for hidden in ('Dashboard', 'Master Data', 'Import Students', 'Faculty Account', 'Semester Management'):
			self.assertNotIn(hidden, faculty_html)

		self.client.force_login(self.superuser)
		self.assertContains(self.client.get(self.url), 'Faculty Account')

	def test_faculty_cannot_open_other_pages(self):
		for url in ('/', '/all_students/', '/import_students/', '/semesters/', '/faculty/account/'):
			with self.subTest(url=url):
				self.assertEqual(self.client.get(url).status_code, 403)

class FacultyAccountTests(TestCase):
	"""Only a superuser may create the faculty login or see / change its username and password."""

	def setUp(self):
		User = get_user_model()
		self.superuser = User.objects.create_superuser('admin', 'a@example.com', 'pw-admin-123')
		self.url = reverse('faculty-account')
		self.client.force_login(self.superuser)

	def _create(self, username='iitgn-faculty', password='Sunrise-Falcon-42'):
		return self.client.post(self.url, {'username': username, 'password': password})

	def test_page_offers_creation_when_no_faculty_account_exists(self):
		response = self.client.get(self.url)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'No faculty account exists yet')
		self.assertIsNone(response.context['account'])

	def test_superuser_creates_the_faculty_account(self):
		response = self._create()

		self.assertRedirects(response, f'{self.url}?saved=1')
		account = FacultyAccount.current()
		self.assertEqual(account.user.username, 'iitgn-faculty')
		self.assertFalse(account.user.is_staff)
		self.assertFalse(account.user.is_superuser)
		self.assertTrue(account.user.check_password('Sunrise-Falcon-42'))
		self.assertNotEqual(account.user.password, 'Sunrise-Falcon-42')  # real login password is hashed

	def test_faculty_can_log_in_and_lands_on_the_live_sheet(self):
		self._create()
		self.client.logout()

		response = self.client.post(reverse('login'), {'username': 'iitgn-faculty', 'password': 'Sunrise-Falcon-42'})

		self.assertRedirects(response, reverse('live-sheet'), fetch_redirect_response=False)
		self.assertEqual(self.client.get(reverse('live-sheet')).status_code, 200)

	def test_superuser_never_sees_the_password(self):
		self._create()

		response = self.client.get(self.url)

		self.assertContains(response, 'iitgn-faculty')
		self.assertNotContains(response, 'Sunrise-Falcon-42')
		self.assertEqual(response.context['form']['password'].value(), None)

	def test_superuser_can_change_username_and_password(self):
		self._create()
		user_id = FacultyAccount.current().user_id

		response = self._create(username='faculty-2027', password='Maple-Harbor-77')

		self.assertRedirects(response, f'{self.url}?saved=1')
		account = FacultyAccount.current()
		self.assertEqual(account.user_id, user_id)  # same account, not a second one
		self.assertEqual(FacultyAccount.objects.count(), 1)
		self.assertEqual(account.user.username, 'faculty-2027')
		self.client.logout()
		self.assertFalse(self.client.login(username='iitgn-faculty', password='Sunrise-Falcon-42'))
		self.assertTrue(self.client.login(username='faculty-2027', password='Maple-Harbor-77'))
		self.assertEqual(self.client.get(reverse('live-sheet')).status_code, 200)  # still has access

	def test_blank_password_keeps_existing_password(self):
		self._create()

		response = self.client.post(self.url, {'username': 'faculty-renamed', 'password': ''})

		self.assertRedirects(response, f'{self.url}?saved=1')
		account = FacultyAccount.current()
		self.assertEqual(account.user.username, 'faculty-renamed')
		self.assertTrue(account.user.check_password('Sunrise-Falcon-42'))

	def test_username_cannot_clash_with_another_user(self):
		response = self._create(username='ADMIN')

		self.assertContains(response, 'Another user already has this username.')
		self.assertIsNone(FacultyAccount.current())

	def test_weak_password_is_rejected(self):
		response = self._create(password='12345678')

		self.assertEqual(response.status_code, 200)
		self.assertIn('password', response.context['form'].errors)
		self.assertIsNone(FacultyAccount.current())

	def test_faculty_cannot_see_or_change_the_credentials(self):
		self._create()
		self.client.logout()
		self.client.login(username='iitgn-faculty', password='Sunrise-Falcon-42')

		get = self.client.get(self.url)
		post = self.client.post(self.url, {'username': 'hijacked', 'password': 'Maple-Harbor-77'})

		self.assertEqual(get.status_code, 403)
		self.assertNotContains(get, 'Sunrise-Falcon-42', status_code=403)
		self.assertEqual(post.status_code, 403)
		self.assertEqual(FacultyAccount.current().user.username, 'iitgn-faculty')
		self.assertNotContains(self.client.get(reverse('live-sheet')), 'Sunrise-Falcon-42')

	def test_other_users_cannot_open_the_page(self):
		get_user_model().objects.create_user('outsider', password='pw-12345-x')
		self.client.logout()
		self.client.login(username='outsider', password='pw-12345-x')

		self.assertEqual(self.client.get(self.url).status_code, 403)

	def test_anonymous_visitor_is_sent_to_login(self):
		self.client.logout()
		response = self.client.get(self.url)

		self.assertEqual(response.status_code, 302)
		self.assertTrue(response['Location'].startswith(resolve_url(settings.LOGIN_URL)))

	def test_readable_password_is_not_exposed_in_django_admin(self):
		self.assertFalse(admin.site.is_registered(FacultyAccount))

	def test_login_redirects_faculty_to_live_sheet_and_superuser_to_dashboard(self):
		response = self.client.post(reverse('login'), {'username': 'phys', 'password': 'pw-12345-x'})
		self.assertRedirects(response, self.url)
		self.client.logout()
		response = self.client.post(reverse('login'), {'username': 'admin', 'password': 'pw-admin-123'})
		self.assertRedirects(response, reverse('home'))

	def test_health_check_is_available_without_login(self):
		self.client.logout()

		response = self.client.get('/healthz/')

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.content, b'ok')


class NumericCellImportTests(TestCase):
    """Phone numbers / PIN codes read from Excel as floats must not keep a ".0" suffix."""

    def test_float_phone_and_pincode_are_stored_without_decimal(self):
        from .importer import REQUIRED_COLUMNS
        semester = Semester.objects.create(name='Fall 2026', is_active=True)
        row = {column: 'x' for column in REQUIRED_COLUMNS}
        row.update({'Application No': 'A-1', 'First Name': 'Asha', 'Last Name': 'Rao', 'Dob': '2000-01-31',
                    'Email': 'asha@example.com', 'Prephone': 9876543210.0, 'Premobile': 8920000000.0,
                    'Perpincode': 380001.0})
        import_master_excel(excel_bytes(pd.DataFrame([row])), semester=semester)

        student = Student.objects.get(application_no='A-1')
        self.assertEqual((student.contact_no_1, student.contact_no_2, student.pincode),
                         ('9876543210', '8920000000', '380001'))

    def test_clean_numeric_text_command_strips_old_suffix(self):
        from django.core.management import call_command
        semester = Semester.objects.create(name='Fall 2026', is_active=True)
        Student.objects.create(semester=semester, application_no='B-1', full_name='Old Row',
                               contact_no_1='9729198718.0', contact_no_2='99999 99999', pincode='380001.0')
        call_command('clean_numeric_text', apply=True, stdout=io.StringIO())

        student = Student.objects.get(application_no='B-1')
        self.assertEqual((student.contact_no_1, student.contact_no_2, student.pincode),
                         ('9729198718', '99999 99999', '380001'))


class RemoveOfferTests(TestCase):
    def setUp(self):
        self.admin = make_superuser()
        self.client.force_login(self.admin)
        self.semester = Semester.objects.create(name='Fall 2026', is_active=True)
        self.student = Student.objects.create(semester=self.semester, application_no='R-1', full_name='Remove Me',
                                              discipline='CS', email='a-very-long-email-address@example-institute.ac.in',
                                              permanent_address_line_1='Flat 204, Meghna Heights, Sector 17, Near Central Market')
        self.offer = Offer.create_for_student(self.student)

    def test_button_is_shown_and_full_values_are_not_cut(self):
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'Remove offer')
        self.assertContains(response, reverse('offer-remove', args=[self.offer.pk]))
        self.assertContains(response, 'a-very-long-email-address@example-institute.ac.in')
        self.assertContains(response, 'Flat 204, Meghna Heights, Sector 17, Near Central Market')

    def test_removing_deletes_the_offer_but_keeps_the_applicant(self):
        response = self.client.post(reverse('offer-remove', args=[self.offer.pk]))
        self.assertRedirects(response, reverse('home'))
        self.assertFalse(Offer.objects.filter(pk=self.offer.pk).exists())
        self.assertTrue(Student.objects.filter(pk=self.student.pk).exists())
        # the applicant can be offered again
        self.assertTrue(Offer.create_for_student(self.student))

    def test_get_is_not_allowed_and_non_superusers_are_refused(self):
        self.assertEqual(self.client.get(reverse('offer-remove', args=[self.offer.pk])).status_code, 405)
        self.client.logout()
        self.client.force_login(get_user_model().objects.create_user('plain', password='pw-plain-123'))
        response = self.client.post(reverse('offer-remove', args=[self.offer.pk]))
        self.assertIn(response.status_code, (302, 403))
        self.assertTrue(Offer.objects.filter(pk=self.offer.pk).exists())
