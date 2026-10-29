from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.urls import reverse


class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        return False  # e-mail/password accounts are created by our own register view

    def get_login_redirect_url(self, request):
        return reverse("jobs:dashboard")


class SocialAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(self, request, sociallogin):
        return True

    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form)
        # an e-mail confirmed by Google/GitHub/Microsoft counts as confirmed here
        user.email_confirmed = True
        if form is not None:
            user.kind = form.cleaned_data.get("kind") or user.kind
        user.check_student_domain()
        user.save(update_fields=["email_confirmed", "kind", "student_verified"])
        return user

    def get_connect_redirect_url(self, request, socialaccount):
        return reverse("accounts:two_factor_setup")
