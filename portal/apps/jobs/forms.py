from django import forms
from django.conf import settings


class UploadForm(forms.Form):
    file = forms.FileField(label="Plik .fds")

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
