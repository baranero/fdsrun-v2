from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import User


class RegisterForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("email", "kind")
        labels = {"email": "E-mail", "kind": "Rodzaj konta"}


class SocialSignupForm(forms.Form):
    """Shown once, on the first login through Google/GitHub/Microsoft: pick the account type."""

    kind = forms.ChoiceField(label="Rodzaj konta", choices=User.Kind.choices, initial=User.Kind.COMPANY)

    def __init__(self, *args, **kwargs):
        self.sociallogin = kwargs.pop("sociallogin", None)
        super().__init__(*args, **kwargs)

    def signup(self, request, user):
        user.kind = self.cleaned_data["kind"]
        user.save(update_fields=["kind"])
