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
    ├── shopify_admin.py     connexion à l'API Admin (vraies quantités)
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

## Connecter les vrais stocks Shopify

Sans connexion, le PDF indique seulement la disponibilité (« Disponible », « Épuisé »).
Une fois ta boutique connectée, les produits sont lus **directement dans Shopify** (plus de
blocage anti-robots du site public) et le PDF affiche les quantités réelles, détaillées par
taille (ex. `12 en stock · S : 4, M : 8`). Les brouillons ne sont pas inclus.
Les liens d'autres boutiques continuent de passer par leur site public. Il faut être propriétaire ou membre de l'équipe
de la boutique avec le droit de développer des apps.

### 1. Créer l'app dans le Dev Dashboard (une seule fois)

Depuis janvier 2026, Shopify ne permet plus de créer les anciennes « apps personnalisées »
dans l'admin : on passe par le Dev Dashboard.

1. Ouvre https://dev.shopify.com/dashboard/ (connecté avec le compte de la boutique), menu **Apps**.
2. **Create app** → **Start from Dev Dashboard** → nomme-la (ex. « Catalogue PDF ») → **Create**.
3. Page **Versions** :
   - **App URL** : laisse `https://shopify.dev/apps/default-app-home`
   - **Scopes** : `read_products` et `read_inventory` (lecture seule, rien d'autre)
   - **Release**
4. **Install app** → choisis la boutique Kilometre → **Install**.
5. **Settings** → carte **Credentials** : copie le **Client ID** et le **Client secret**.

### 2. Remplir le fichier `.env`

Copie `.env.example` en `.env` (à côté de `manage.py`) et remplis :

```
SHOPIFY_SHOP=kilometre-paris            # le nom avant .myshopify.com
SHOPIFY_CLIENT_ID=xxxxxxxx
SHOPIFY_CLIENT_SECRET=xxxxxxxx
```

Le nom `.myshopify.com` de la boutique se trouve dans l'admin Shopify :
**Paramètres → Domaines**. Si la boutique a déjà une ancienne app avec un jeton
`shpat_...`, tu peux mettre `SHOPIFY_ACCESS_TOKEN=shpat_...` à la place du Client ID / secret.

Relance le serveur : la page d'accueil affiche « Stocks Shopify connectés ».

### Sécurité

- `.env` est dans `.gitignore` : **ne le mets jamais sur GitHub** et ne partage pas le secret.
- L'app n'a que des droits de **lecture** : elle ne peut rien modifier dans la boutique.
- Le jeton d'accès (valable 24 h) est demandé et renouvelé automatiquement.
- Si la connexion échoue, l'aperçu affiche la raison et le PDF reprend la disponibilité publique.

## Options du formulaire

- **Photo 1 / Photo 2** : numéro de la photo prise sur chaque fiche (1 = la première).
- **Légendes** : texte sous chaque photo (« Devant », « Dos », « Porté »…).
- **Devise** : Shopify ne donne pas la devise dans ses données publiques.

## Limites

- **Quantités** : non publiques sur Shopify. Sans connexion, le PDF indique « Disponible »,
  « Épuisé » ou les tailles disponibles. Pour les vraies quantités, voir « Connecter les vrais
  stocks Shopify » (uniquement pour ta propre boutique).
- **Protection anti-robots** : certaines boutiques bloquent les requêtes automatiques ;
  l'appli affiche alors un message, réessaie plus tard.
- Maximum 500 produits par PDF.

## Mise en ligne

Avant de publier : dans `config/settings.py`, mets `DEBUG = False`, remplace la
`SECRET_KEY` par une valeur secrète et ajoute ton domaine dans `ALLOWED_HOSTS`.
