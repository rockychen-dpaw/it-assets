from django import forms

from . import models


class LeakRuleEditForm(forms.ModelForm):
    class Meta:
        model = models.LeakRule
        fields = "__all__"
        widgets = {
            "regex":forms.TextInput(attrs={"style":"width:80%"})
        }


class ExcludedFileEditForm(forms.ModelForm):
    class Meta:
        model = models.LeakRule
        fields = "__all__"
        widgets = {
            "regex":forms.TextInput(attrs={"style":"width:80%"})
        }




