import re

from django import forms

from .models import EU, BillingProfile

COUNTRIES = [("PL", "Polska")] + sorted([(c, c) for c in EU]) + [("CH", "CH"), ("GB", "GB"), ("NO", "NO"), ("UA", "UA"), ("US", "US"), ("XX", "inny (spoza UE)")]


class BillingForm(forms.ModelForm):
    country = forms.ChoiceField(label="Kraj", choices=COUNTRIES)

    class Meta:
        model = BillingProfile
        fields = ("kind", "name", "nip", "vat_eu", "street", "postcode", "city", "country", "invoice_email", "mode")
        widgets = {"kind": forms.RadioSelect, "mode": forms.RadioSelect}

    def clean_nip(self):
        nip = self.cleaned_data.get("nip", "").strip()
        if self.cleaned_data.get("country", "PL") == "PL" and nip:
            nip = re.sub(r"\D", "", nip)
            if len(nip) != 10:
                raise forms.ValidationError("Polski NIP ma 10 cyfr.")
        return nip

    def clean(self):
        d = super().clean()
        if d.get("kind") == BillingProfile.Kind.COMPANY and not d.get("nip"):
            self.add_error("nip", "Dla firmy podaj NIP (albo numer podatkowy z Twojego kraju).")
        if d.get("kind") == BillingProfile.Kind.PERSON:
            d["mode"] = BillingProfile.Mode.PER_JOB  # monthly invoices are for companies
        return d
