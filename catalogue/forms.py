from django import forms

CURRENCIES = [("€", "€"), ("$", "$"), ("£", "£"), ("CHF", "CHF")]


class CatalogueForm(forms.Form):
    url = forms.CharField(
        label="Lien",
        max_length=500,
        widget=forms.TextInput(attrs={"placeholder": "https://boutique.com/collections/nouveautes"}),
    )
    img1 = forms.IntegerField(label="Photo 1 (n°)", min_value=1, initial=1)
    lab1 = forms.CharField(label="Légende 1", max_length=40, initial="Devant")
    img2 = forms.IntegerField(label="Photo 2 (n°)", min_value=1, initial=2)
    lab2 = forms.CharField(label="Légende 2", max_length=40, initial="Dos")
    cur = forms.ChoiceField(label="Devise", choices=CURRENCIES, initial="€")
