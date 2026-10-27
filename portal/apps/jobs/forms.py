from django import forms
from django.conf import settings


class UploadForm(forms.Form):
    file = forms.FileField(label="Plik .fds")
    project = forms.CharField(label="Projekt (folder)", required=False, max_length=120, help_text="Nazwa istniejącego lub nowego projektu; można zostawić puste.")

    def clean_file(self):
        f = self.cleaned_data["file"]
        if not f.name.lower().endswith(".fds"):
            raise forms.ValidationError("Wgraj plik z rozszerzeniem .fds (eksport z PyroSim).")
        if f.size > settings.MAX_UPLOAD_MB * 1024 * 1024:
            raise forms.ValidationError(f"Plik jest większy niż {settings.MAX_UPLOAD_MB} MB.")
        return f


class StartForm(forms.Form):
    procs = forms.IntegerField(min_value=1, max_value=64)
    server_type = forms.ChoiceField(choices=[("cpx32", "cpx32"), ("cpx42", "cpx42"), ("cpx62", "cpx62")])


class JobEditForm(forms.Form):
    name = forms.CharField(label="Nazwa zlecenia", max_length=120)
    project = forms.CharField(label="Projekt (folder)", required=False, max_length=120)
    note = forms.CharField(label="Notatka", required=False, widget=forms.Textarea(attrs={"rows": 3}), max_length=2000)
