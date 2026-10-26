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
    trusted = models.BooleanField(default=False, help_text="Zaufana firma: pobieranie w trakcie i faktura zbiorcza")
    per_job_limit_pln = models.DecimalField(max_digits=9, decimal_places=2, default=300)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []
    objects = UserManager()

    def __str__(self):
        return self.email
