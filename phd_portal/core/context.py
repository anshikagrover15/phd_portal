from .models import Semester


def active_semester(request):
    """Active semester shown in the top bar (superusers only)."""
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated or not user.is_superuser:
        return {}
    return {'active_semester_nav': Semester.objects.filter(is_active=True).first()}
