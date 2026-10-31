from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

class Semester(models.Model):
    name = models.CharField(max_length=255, unique=True)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def clean(self):
        super().clean()
        if self.is_active and Semester.objects.filter(is_active=True).exclude(pk=self.pk).exists():
            raise ValidationError({'is_active': 'Only one active semester can exist at a time.'})

    def __str__(self):
        return self.name

class Student(models.Model):
    semester = models.ForeignKey(Semester, on_delete=models.PROTECT, null=True, blank=True, related_name='students')
    application_no = models.CharField(max_length=255, unique=True)
    program = models.CharField(max_length=255, blank=True)
    sub_programme = models.CharField(max_length=255, blank=True)
    discipline = models.CharField(max_length=255, blank=True)
    research_area = models.TextField(blank=True)
    first_name = models.CharField(max_length=255, blank=True)
    middle_name = models.CharField(max_length=255, blank=True)
    last_name = models.CharField(max_length=255, blank=True)
    full_name = models.CharField(max_length=255)
    category = models.CharField(max_length=255, blank=True)
    dob = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=50, blank=True)
    contact_no_1 = models.CharField(max_length=50, blank=True)
    contact_no_2 = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True, default='')
    permanent_address_line_1 = models.TextField(blank=True)
    address_line_2 = models.TextField(blank=True)
    city = models.CharField(max_length=255, blank=True)
    pincode = models.CharField(max_length=50, blank=True)
    state = models.CharField(max_length=255, blank=True)
    status_of_application = models.CharField(max_length=255, blank=True)
    iitgn_email_id = models.EmailField(blank=True, default='')


    def clean(self):
        super().clean()
        if not self.application_no or not self.application_no.strip():
            raise ValidationError({'application_no': 'Application No is required.'})
        if not self.full_name or not self.full_name.strip():
            raise ValidationError({'full_name': 'Full name is required.'})

    def __str__(self):
        return f'{self.application_no} - {self.full_name}'

class Offer(models.Model):
    VALID_WITHDRAWAL_STATUSES = {'', 'withdrawn'}

    student = models.OneToOneField(Student, on_delete=models.CASCADE, related_name='offer')
    semester = models.ForeignKey(Semester, on_delete=models.PROTECT, related_name='offers')
    sr_no = models.CharField(
        max_length=50,
        blank=True
    )
    dis_sr_no = models.CharField(max_length=255)
    fees_paid = models.BooleanField(default=False)
    fees_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # The student's earliest successful payment, kept across imports.
    first_fees_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    first_fees_paid_on = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=255, blank=True)
    withdrawal_status = models.CharField(max_length=50, blank=True)
    remarks = models.TextField(blank=True)
    roll_no = models.CharField(max_length=255, blank=True)
    admission_offered_category = models.CharField(max_length=255, blank=True)
    expected_date_of_joining = models.DateField(null=True, blank=True)
    fellowship_details = models.TextField(blank=True)
    supervisor_details = models.TextField(blank=True)
    area = models.CharField(max_length=255, blank=True)
    fees_deadline = models.DateField(null=True, blank=True)
    fellowship_fund = models.CharField(max_length=255, blank=True)
    date_of_joining = models.DateField(null=True, blank=True)
    is_iitgn_student = models.BooleanField(default=False)
    project_staff = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['student'], name='unique_offer_per_student'),
        ]

    def clean(self):
        super().clean()
        if self.withdrawal_status not in self.VALID_WITHDRAWAL_STATUSES:
            raise ValidationError({'withdrawal_status': 'Withdrawal status must be blank or withdrawn.'})

    @staticmethod
    def _discipline_code(student_or_discipline):
        discipline = student_or_discipline.discipline if hasattr(student_or_discipline, 'discipline') else student_or_discipline
        return str(discipline).strip() or 'General'

    @classmethod
    def _next_dis_sr_number(cls, semester, discipline):
        discipline_code = cls._discipline_code(discipline)
        prefix = discipline_code.split('-')[-1].strip() if '-' in discipline_code else discipline_code
        max_number = 0
        for offer in Offer.objects.filter(semester=semester):
            current = offer.dis_sr_no.strip()
            if not current.startswith(prefix):
                continue
            suffix = current[len(prefix):].strip()
            if suffix.isdigit():
                max_number = max(max_number, int(suffix))
        return max_number + 1

    @classmethod
    def create_for_student(cls, student, semester=None):
        if Offer.objects.filter(student=student).exists():
            raise ValueError('This student already has an offer.')

        if semester is None:
            semester = student.semester or Semester.objects.filter(is_active=True).first()
            if semester is None:
                raise ValueError('There must be an active semester before creating an offer.')

        number = cls._next_dis_sr_number(semester, student)
        prefix = cls._discipline_code(student).split('-')[-1].strip() if '-' in cls._discipline_code(student) else cls._discipline_code(student)
        offer = cls(student=student, semester=semester, dis_sr_no=f'{prefix} {number}')
        offer.full_clean()
        offer.save()
        return offer

    def __str__(self):
        return f'{self.student.application_no} - {self.dis_sr_no}'
    
class FacultyAccount(models.Model):
    """The one shared faculty login. Only this user (and superusers) may open the live sheet."""
    SINGLETON_PK = 1

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='faculty_account')
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def current(cls):
        """The faculty account, or None if the superuser has not created it yet."""
        return cls.objects.select_related('user').filter(pk=cls.SINGLETON_PK).first()

    def __str__(self):
        return f'Faculty account ({self.user.get_username()})'