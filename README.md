# Shopify → PDF (Django)

Colle le lien d'une boutique, d'une collection ou d'un produit Shopify et récupère
un PDF catalogue : 2 photos par produit, nom, collection, prix (et prix barré),
tailles et disponibilité.

## Installation (une seule fois)

Python 3.10 ou plus récent.

```bash
cd shopify_pdf
python -m venv venv
# Windows : venv\Scripts\activate     Mac/Linux : source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
```

## Lancer

```bash
python manage.py runserver
```

Puis ouvre http://127.0.0.1:8000

## Organisation du code

```
shopify_pdf/
├── manage.py
├── requirements.txt
├── config/                  réglages du projet (settings.py, urls.py)
└── catalogue/               l'application
    ├── services.py          récupération Shopify + génération du PDF
    ├── forms.py             le formulaire (lien, photos, légendes, devise)
    ├── views.py             la page : affiche le formulaire, renvoie le PDF
    ├── urls.py
    └── templates/catalogue/index.html
```

Pour changer la mise en page du PDF, tout se passe dans `build_pdf()` de `services.py`.

## Direction artistique

Le site et le PDF reprennent la DA de kilometre.paris : texte bleu `#284991`, accents
rouges `#D40505`, jaune `#FBFBB3`, police Roboto, angles droits, majuscules espacées.

- Couleurs du PDF : en haut de la partie PDF de `services.py` (BLUE, RED, YELLOW…)
- Couleurs du site : variables `:root` en haut des deux templates
- Logo : `catalogue/assets/logo.png` (PDF) et `catalogue/static/catalogue/logo.png` (site)
- Polices du PDF : `catalogue/assets/Roboto-*.ttf` (licence Apache 2.0 incluse)

## Options du formulaire

- **Photo 1 / Photo 2** : numéro de la photo prise sur chaque fiche (1 = la première).
- **Légendes** : texte sous chaque photo (« Devant », « Dos », « Porté »…).
- **Devise** : Shopify ne donne pas la devise dans ses données publiques.

## Limites

- **Quantités** : non publiques sur Shopify. Le PDF indique « Disponible », « Épuisé »
  ou les tailles disponibles. Les vraies quantités demandent l'API Admin de ta propre boutique.
- **Protection anti-robots** : certaines boutiques bloquent les requêtes automatiques ;
  l'appli affiche alors un message, réessaie plus tard.
- Maximum 500 produits par PDF.

## Mise en ligne

Avant de publier : dans `config/settings.py`, mets `DEBUG = False`, remplace la
`SECRET_KEY` par une valeur secrète et ajoute ton domaine dans `ALLOWED_HOSTS`.
