from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.db import transaction

from .models import *


class SemesterForm(forms.ModelForm):
    class Meta:
        model = Semester
        fields = ['name', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'e.g. 2026-27 Semester 1'}),
        }
    
class StudentForm(forms.ModelForm):
    class Meta:
        model = Student
        fields = [
            'full_name', 'program', 'discipline', 'category', 'dob', 'gender',
            'contact_no_1', 'contact_no_2', 'email',
            'permanent_address_line_1', 'address_line_2',
            'city', 'pincode', 'state',
            'status_of_application',
        ]
        widgets = {
            'dob': forms.DateInput(attrs={'type': 'date'}),
        }

class FacultyAccountForm(forms.Form):
    """Create the single faculty login or change its username and password."""
    username = forms.CharField(max_length=150, validators=[UnicodeUsernameValidator()])
    password = forms.CharField(
        max_length=128,
        required=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
    )

    def __init__(self, *args, account=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.account = account
        self.fields['password'].required = account is None
        if account is not None and not self.is_bound:
            self.initial = {'username': account.user.get_username()}

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        taken = get_user_model().objects.filter(username__iexact=username)
        if self.account is not None:
            taken = taken.exclude(pk=self.account.user_id)
        if taken.exists():
            raise forms.ValidationError('Another user already has this username.')
        return username

    def clean_password(self):
        password = self.cleaned_data['password']
        if not password and self.account is not None:
            return password
        validate_password(password, user=self.account.user if self.account else None)
        return password

    def save(self):
        data = self.cleaned_data
        with transaction.atomic():
            if self.account is None:
                user = get_user_model().objects.create_user(
                    username=data['username'], password=data['password'], is_staff=False, is_superuser=False,
                )
                return FacultyAccount.objects.create(
                    pk=FacultyAccount.SINGLETON_PK, user=user,
                )
            user = self.account.user
            user.username = data['username']
            if data['password']:
                user.set_password(data['password'])
            user.save()
            self.account.save()
            return self.account