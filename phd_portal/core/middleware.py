from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.urls import reverse


class LoginRequiredMiddleware:
    """Redirect anonymous users to the login page for every URL."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            path = request.path_info
            exempt_prefixes = (
                reverse('login'),      # the login page itself
                '/admin/',             # admin has its own login
                settings.STATIC_URL,   # css and js files
            )
            if path != '/healthz/' and not path.startswith(exempt_prefixes):
                return redirect_to_login(request.get_full_path())
        return self.get_response(request)