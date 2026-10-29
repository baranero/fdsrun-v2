from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("E-mail jest wymagany")
        user = self.model(email=self.normalize_email(email), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self._create_user(email, password, **extra)


class User(AbstractUser):
    """E-mail is the login. Account type drives pricing and invoicing (stage 3)."""

    class Kind(models.TextChoices):
        COMPANY = "company", _("Firma")
        STUDENT = "student", _("Student")
        PERSON = "person", _("Osoba prywatna")

    username = None
    email = models.EmailField(_("e-mail"), unique=True)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.COMPANY)
    language = models.CharField(max_length=2, default="pl")
    email_confirmed = models.BooleanField(default=False)
    totp_secret = models.CharField(max_length=64, blank=True)  # set = 2FA enabled
    totp_backup = models.CharField(max_length=200, blank=True, help_text="hashed one-time backup codes, comma separated")
    student_verified = models.BooleanField(default=False, help_text="Status studenta potwierdzony (domena uczelni albo administrator)")
    trusted = models.BooleanField(default=False, help_text="Zaufany klient: bez limitu nieopłaconego salda")
    per_job_limit_pln = models.DecimalField("Limit nieopłaconego salda [zł]", max_digits=9, decimal_places=2, default=500,
                                            help_text="Obowiązuje do pierwszej zapłaconej faktury (D-11)")

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []
    objects = UserManager()

    def __str__(self):
        return self.email

    def check_student_domain(self):
        """Set student_verified when the e-mail belongs to an academic domain (decision 29.10)."""
        from fnmatch import fnmatch

        from django.conf import settings

        domain = "." + self.email.rsplit("@", 1)[-1].lower()
        if self.kind == self.Kind.STUDENT and any(fnmatch(domain, "*" + d) for d in settings.STUDENT_DOMAINS):
            self.student_verified = True
        return self.student_verified

    @property
    def two_factor_enabled(self):
        return bool(self.totp_secret)
