from django.contrib.auth.backends import ModelBackend

from .models import User


class EmailOrUsernameBackend(ModelBackend):
    """Allow logging in with either username or e-mail."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username and "@" in username:
            user = User.objects.filter(email__iexact=username).first()
            if user:
                username = user.get_username()
        return super().authenticate(request, username=username, password=password, **kwargs)
