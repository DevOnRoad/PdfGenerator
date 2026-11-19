"""
Connexion à l'API Admin de TA boutique Shopify pour récupérer les vraies quantités.

Deux façons de se connecter (réglages dans le fichier .env, voir README) :
  1. Méthode actuelle : une app créée dans le Dev Dashboard de Shopify
       SHOPIFY_SHOP, SHOPIFY_CLIENT_ID, SHOPIFY_CLIENT_SECRET
     Le jeton d'accès (valable 24 h) est demandé et renouvelé automatiquement.
  2. Ancienne app personnalisée (créée avant 2026) : un jeton "shpat_..."
       SHOPIFY_SHOP, SHOPIFY_ACCESS_TOKEN

Sans ces réglages, l'outil marche comme avant (disponibilité seulement).
"""
import os
import time

import requests

API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "2026-10")
TIMEOUT = 25
BATCH = 250  # nombre max d'identifiants par requête GraphQL "nodes"

_token_cache = {"token": None, "expires": 0.0}


class AdminError(Exception):
    pass


def _shop():
    """'kilometre-paris' ou 'kilometre-paris.myshopify.com' -> 'kilometre-paris.myshopify.com'."""
    shop = os.environ.get("SHOPIFY_SHOP", "").strip().lower()
    shop = shop.replace("https://", "").replace("http://", "").strip("/")
    if shop and not shop.endswith(".myshopify.com"):
        shop += ".myshopify.com"
    return shop


def is_configured():
    return bool(_shop() and (os.environ.get("SHOPIFY_ACCESS_TOKEN")
                             or (os.environ.get("SHOPIFY_CLIENT_ID")
                                 and os.environ.get("SHOPIFY_CLIENT_SECRET"))))


def _token():
    static = os.environ.get("SHOPIFY_ACCESS_TOKEN", "").strip()
    if static:
        return static
    if _token_cache["token"] and time.time() < _token_cache["expires"]:
        return _token_cache["token"]
    try:
        r = requests.post(
            f"https://{_shop()}/admin/oauth/access_token",
            data={"grant_type": "client_credentials",
                  "client_id": os.environ.get("SHOPIFY_CLIENT_ID", "").strip(),
                  "client_secret": os.environ.get("SHOPIFY_CLIENT_SECRET", "").strip()},
            timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        raise AdminError(f"Impossible de joindre Shopify ({e.__class__.__name__}).")
    if r.status_code != 200:
        raise AdminError("Shopify a refusé la connexion : vérifie SHOPIFY_SHOP, le Client ID, "
                         "le Client secret, et que l'app est bien installée sur la boutique.")
    data = r.json()
    if "read_inventory" not in data.get("scope", ""):
        raise AdminError("L'app Shopify n'a pas l'autorisation « read_inventory » : "
                         "ajoute-la dans le Dev Dashboard, publie une nouvelle version "
                         "et accepte-la sur la boutique.")
    _token_cache["token"] = data["access_token"]
    _token_cache["expires"] = time.time() + int(data.get("expires_in", 86399)) - 60
    return _token_cache["token"]


def _graphql(query, variables, _retry=0):
    try:
        r = requests.post(
            f"https://{_shop()}/admin/api/{API_VERSION}/graphql.json",
            json={"query": query, "variables": variables},
            headers={"X-Shopify-Access-Token": _token()},
            timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        raise AdminError(f"Impossible de joindre Shopify ({e.__class__.__name__}).")
    if r.status_code in (401, 403):
        _token_cache["token"] = None
        raise AdminError("Accès refusé par Shopify : jeton invalide ou autorisation "
                         "« read_inventory » / « read_products » manquante.")
    if r.status_code != 200:
        raise AdminError(f"Erreur Shopify ({r.status_code}).")
    data = r.json()
    errors = str(data.get("errors") or "")
    if "THROTTLED" in errors and _retry < 5:  # trop de requêtes : on patiente puis on réessaie
        time.sleep(2 + _retry * 2)
        return _graphql(query, variables, _retry + 1)
    throttle = ((data.get("extensions") or {}).get("cost") or {}).get("throttleStatus") or {}
    if throttle and throttle.get("currentlyAvailable", 1000) < 400:
        time.sleep(min(10, (400 - throttle["currentlyAvailable"]) / max(throttle.get("restoreRate", 50), 1)))
    if data.get("errors"):
        msg = str(data["errors"])
        if "ACCESS_DENIED" in msg:
            raise AdminError("Autorisation manquante : l'app doit avoir « read_products » "
                             "et « read_inventory ».")
        raise AdminError(f"Erreur Shopify : {msg[:200]}")
    return data["data"]


# ---------------------------------------------------------------- produits via l'API Admin
# Avec la connexion, on lit les produits directement dans la boutique au lieu de passer par
# le site public : plus de blocage anti-robots, et les quantités arrivent en même temps.

PRODUCT_FIELDS = """
  id title handle productType status
  options { name optionValues { name } }
  media(first: 30) { nodes { ... on MediaImage { id image { url altText } } } }
  variants(first: 100) {
    nodes {
      id title price compareAtPrice availableForSale inventoryQuantity
      inventoryItem { tracked }
      selectedOptions { name value }
      media(first: 1) { nodes { ... on MediaImage { id } } }
    }
  }
"""
PAGE = 6  # produits par requête (limite de "coût" de l'API Shopify)

Q_COLLECTION = """
query Coll($q: String!, $after: String) {
  collections(first: 5, query: $q) {
    nodes {
      handle title
      products(first: %d, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes { %s }
      }
    }
  }
}""" % (PAGE, PRODUCT_FIELDS)

Q_PRODUCTS = """
query Prods($q: String!, $after: String) {
  products(first: %d, after: $after, query: $q) {
    pageInfo { hasNextPage endCursor }
    nodes { %s }
  }
}""" % (PAGE, PRODUCT_FIELDS)


def _num(gid):
    return int(str(gid).rsplit("/", 1)[-1])


def _to_public(node):
    """Produit de l'API Admin -> même format que le JSON public (products.json),
    pour que le reste du code ne change pas."""
    opt_names = [o["name"] for o in node.get("options") or []]
    images = []
    for m in (node.get("media") or {}).get("nodes") or []:
        if m and m.get("image"):
            images.append({"id": m["id"], "src": m["image"]["url"],
                           "alt": m["image"].get("altText") or "", "variant_ids": []})
    variants = []
    for v in (node.get("variants") or {}).get("nodes") or []:
        sel = {s["name"]: s["value"] for s in v.get("selectedOptions") or []}
        media = ((v.get("media") or {}).get("nodes") or [None])[0] or {}
        tracked = (v.get("inventoryItem") or {}).get("tracked")
        item = {
            "id": _num(v["id"]),
            "title": v.get("title") or "",
            "price": v.get("price"),
            "compare_at_price": v.get("compareAtPrice"),
            "available": bool(v.get("availableForSale")),
            "featured_image": {"id": media["id"]} if media.get("id") else None,
        }
        for k, name in enumerate(opt_names[:3]):
            item[f"option{k + 1}"] = sel.get(name)
        if tracked:
            item["inventory_quantity"] = v.get("inventoryQuantity") or 0
        variants.append(item)
    return {
        "title": node.get("title", ""),
        "handle": node.get("handle"),
        "product_type": node.get("productType") or "",
        "options": [{"name": o["name"], "values": [x["name"] for x in o.get("optionValues") or []]}
                    for o in node.get("options") or []],
        "images": images,
        "variants": variants,
    }


def fetch_products_admin(kind, handle, limit=500):
    """Retourne (produits, titre de collection) depuis l'API Admin,
    ou None si ce lien ne correspond à rien dans la boutique connectée."""
    if not is_configured():
        return None
    nodes, title, after = [], None, None
    while len(nodes) < limit:
        if kind == "collection" and handle != "all":
            data = _graphql(Q_COLLECTION, {"q": f"handle:'{handle}'", "after": after})
            coll = next((c for c in data["collections"]["nodes"] if c["handle"] == handle), None)
            if not coll:
                return None
            title, page = coll["title"], coll["products"]
        else:
            q = f"handle:'{handle}'" if kind == "product" else "status:active"
            page = _graphql(Q_PRODUCTS, {"q": q, "after": after})["products"]
        nodes += page["nodes"]
        if kind == "product" or not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    if kind == "product":
        nodes = [n for n in nodes if n.get("handle") == handle]
    nodes = [n for n in nodes if n.get("status", "ACTIVE") == "ACTIVE"]  # pas de brouillons
    if not nodes:
        return None
    return [_to_public(n) for n in nodes[:limit]], title
