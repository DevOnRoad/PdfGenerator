"""Récupération des produits Shopify et génération du PDF."""
import datetime
import io
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests
from PIL import Image
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

HEADERS = {"User-Agent": "Mozilla/5.0 (catalogue-pdf)"}
TIMEOUT = 25
MAX_PRODUCTS = 500


# ---------------------------------------------------------------- récupération
class ShopError(Exception):
    pass


def parse_url(url):
    """Retourne (base, kind, handle) : kind = 'collection' | 'product' | 'shop'."""
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    u = urlparse(url)
    base = f"{u.scheme}://{u.netloc}"
    m = re.search(r"/collections/([^/?#]+)", u.path)
    p = re.search(r"/products/([^/?#]+)", u.path)
    if p:
        return base, "product", p.group(1)
    if m:
        return base, "collection", m.group(1)
    return base, "shop", None


def get_json(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise ShopError(f"Impossible de joindre le site ({e.__class__.__name__}).")
    if r.status_code == 429 or "Verifying your connection" in r.text[:2000]:
        raise ShopError("Le site bloque les requêtes automatiques pour le moment "
                        "(protection anti-robots). Réessaie plus tard.")
    if r.status_code == 404:
        raise ShopError("Page introuvable : vérifie le lien.")
    try:
        return r.json()
    except ValueError:
        raise ShopError("Ce site ne semble pas être une boutique Shopify "
                        "(pas de données produits lisibles).")


def fetch_products(base, kind, handle):
    if kind == "product":
        data = get_json(f"{base}/products/{handle}.json")
        return [data["product"]]
    path = f"/collections/{handle}/products.json" if kind == "collection" else "/products.json"
    products, page = [], 1
    while len(products) < MAX_PRODUCTS:
        data = get_json(f"{base}{path}?limit=250&page={page}")
        batch = data.get("products", [])
        if not batch:
            break
        products += batch
        if len(batch) < 250:
            break
        page += 1
    if not products:
        raise ShopError("Aucun produit trouvé à cette adresse.")
    return products[:MAX_PRODUCTS]


def collection_title(base, kind, handle):
    if kind != "collection":
        return None
    try:
        return get_json(f"{base}/collections/{handle}.json")["collection"]["title"]
    except Exception:
        return handle.replace("-", " ").title()


def sized(src, width=900):
    sep = "&" if "?" in src else "?"
    return f"{src}{sep}width={width}"


def download_image(src):
    try:
        r = requests.get(sized(src), headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        im = Image.open(io.BytesIO(r.content)).convert("RGB")
        im.thumbnail((900, 900))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=82)
        buf.seek(0)
        return buf
    except Exception:
        return None


SIZE_WORDS = ("taille", "size", "pointure", "longueur", "length", "tour", "waist", "inseam")
DEFAULT_VALUES = {"default title", "default", ""}


def _slug(text):
    """'Bleu Marine' -> 'bleumarine' (sans accents ni espaces) pour comparer des noms."""
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", text)


def _visual_option(p):
    """Index (0, 1 ou 2) de l'option qui change l'apparence (couleur, motif...), sinon None.
    On prend la première option qui n'est pas une taille et qui a au moins 2 valeurs."""
    for i, opt in enumerate(p.get("options", [])[:3]):
        name = _slug(opt.get("name", ""))
        values = [v for v in opt.get("values", []) if _slug(v) not in {_slug(d) for d in DEFAULT_VALUES}]
        if len(values) < 2 or name == "title":
            continue
        if any(w in name for w in SIZE_WORDS):
            continue
        return i
    return None


def _size_label(v, skip):
    parts = [v.get(f"option{k + 1}") for k in range(3) if k != skip]
    parts = [x for x in parts if x and _slug(x) not in {_slug(d) for d in DEFAULT_VALUES}]
    return " / ".join(parts)


def _stock(variants, sizes):
    qty = [v.get("inventory_quantity") for v in variants if v.get("inventory_quantity") is not None]
    available = [v for v in variants if v.get("available")]
    if qty:
        return f"{sum(qty)} en stock"
    if not available:
        return "Épuisé"
    if sizes and len(available) < len(variants):
        return "Disponible : " + ", ".join(s for v, s in zip(variants, sizes) if v.get("available"))
    return "Disponible (toutes tailles)" if sizes else "Disponible"


def _variant_images(p, groups, opt_idx):
    """Trouve les photos de chaque couleur. Retourne {valeur: (liste d'urls, source)}.
    Ordre de recherche : photo reliée à la variante -> nom dans le fichier/alt ->
    photos libres de la galerie -> photo principale du produit."""
    images = p.get("images", [])
    srcs = [i["src"] for i in images]
    pos_by_id = {i["id"]: n for n, i in enumerate(images) if "id" in i}

    # 1. photo reliée à une variante du groupe (featured_image / image_id / variant_ids)
    start = {}
    for value, vs in groups.items():
        ids = {v["id"] for v in vs if "id" in v}
        cands = []
        for v in vs:
            img = v.get("featured_image") or {}
            if img.get("id") in pos_by_id:
                cands.append(pos_by_id[img["id"]])
            elif v.get("image_id") in pos_by_id:
                cands.append(pos_by_id[v["image_id"]])
        cands += [n for n, i in enumerate(images) if ids & set(i.get("variant_ids") or [])]
        if cands:
            start[value] = (min(cands), "reliée")

    # 2. nom de la couleur dans le nom du fichier ou le texte alternatif
    for value in groups:
        if value in start:
            continue
        key = _slug(value)
        if len(key) < 3:
            continue
        taken = {n for n, _ in start.values()}
        for n, i in enumerate(images):
            hay = _slug(i.get("alt") or "") + " " + _slug(i["src"].split("/")[-1].split("?")[0])
            if key in hay and n not in taken:
                start[value] = (n, "nom")
                break

    # Taille d'un "bloc" de photos par couleur (devant, dos, détails...)
    starts = sorted(n for n, _ in start.values())
    gaps = [b - a for a, b in zip(starts, starts[1:]) if b > a]
    block = min(gaps) if gaps else max(1, min(2, len(srcs)))

    used = set()
    result = {}
    for value, (n, how) in start.items():
        nxt = [s for s in starts if s > n]
        end = min(n + block, nxt[0] if nxt else len(srcs))
        result[value] = (srcs[n:end], how)
        used.update(range(n, end))

    # 3. photos libres (non reliées, après la première photo de couleur) pour les couleurs restantes
    first = starts[0] if starts else len(srcs)
    free = [n for n in range(first, len(srcs))
            if n not in used and not images[n].get("variant_ids")]
    for value in groups:
        if value in result:
            continue
        if free:
            chunk, free = free[:block], free[block:]
            result[value] = ([srcs[n] for n in chunk], "devinée")
        else:
            # 4. rien trouvé : photo principale du produit
            result[value] = (srcs[:2], "manquante")
    return result


def normalise(p, coll_name, img_idx):
    """Transforme un produit Shopify en une ou plusieurs fiches pour le PDF.
    Une fiche par couleur (ou motif) ; les tailles restent groupées sur la fiche."""
    variants = p.get("variants", [])
    opt = _visual_option(p)
    base = {"title": p.get("title", ""), "collection": coll_name or p.get("product_type") or "—"}

    def item(vs, variant_label, urls, photo_note, skip):
        prices = sorted({float(v["price"]) for v in vs if v.get("price")})
        compare = [float(v["compare_at_price"]) for v in vs if v.get("compare_at_price")]
        sizes = [_size_label(v, skip) for v in vs]
        sizes = sizes if any(sizes) else []
        return {**base,
                "variant": variant_label,
                "price": prices,
                "compare": max(compare) if compare else None,
                "sizes": sizes,
                "stock": _stock(vs, sizes),
                "image_urls": urls,
                "photo_note": photo_note}

    srcs = [i["src"] for i in p.get("images", [])]

    if opt is None:
        picks = [srcs[i] for i in img_idx if i < len(srcs)]
        it = item(variants, None, picks, None, None)
        it["gallery"] = srcs
        return [it]

    groups = {}
    for v in variants:
        groups.setdefault(v.get(f"option{opt + 1}") or "—", []).append(v)
    found = _variant_images(p, groups, opt)
    opt_name = p["options"][opt].get("name", "Variante")

    out = []
    for value, vs in groups.items():
        urls, how = found[value]
        picks = [urls[i] for i in img_idx if i < len(urls)]
        if not picks and urls:
            picks = urls[:1]
        note = {"devinée": "Photo devinée, à vérifier",
                "manquante": "Pas de photo : photo du produit"}.get(how)
        it = item(vs, f"{opt_name} : {value}", picks, note, opt)
        it["gallery"] = urls + [u for u in srcs if u not in urls]
        out.append(it)
    return out


# ---------------------------------------------------------------- PDF
# Direction artistique inspirée de kilometre.paris
from pathlib import Path
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

ASSETS = Path(__file__).resolve().parent / "assets"
LOGO = ASSETS / "logo.png"

BLUE = HexColor("#284991")       # texte principal
BLUE_SOFT = HexColor("#8a9cc4")  # libellés, légendes
RED = HexColor("#d40505")        # accents, menu
SALE = HexColor("#c20000")       # prix barré
YELLOW = HexColor("#fbfbb3")     # boutons, pied de page
LINE = HexColor("#d7deec")       # séparateurs (bleu très clair)
BG = HexColor("#f5f5f5")         # fond des photos

try:
    for name, file in (("Roboto", "Roboto-Regular"), ("Roboto-Medium", "Roboto-Medium"),
                       ("Roboto-Bold", "Roboto-Bold"), ("Roboto-Italic", "Roboto-RegularItalic")):
        pdfmetrics.registerFont(TTFont(name, str(ASSETS / f"{file}.ttf")))
    F, F_MED, F_BOLD, F_IT = "Roboto", "Roboto-Medium", "Roboto-Bold", "Roboto-Italic"
except Exception:  # polices absentes : on retombe sur Helvetica
    F, F_MED, F_BOLD, F_IT = "Helvetica", "Helvetica-Bold", "Helvetica-Bold", "Helvetica-Oblique"


def fmt_price(prices, cur):
    if not prices:
        return "—"
    f = lambda x: (f"{x:,.2f}".replace(",", " ").replace(".", ",").replace(",00", "")) + f" {cur}"
    return f(prices[0]) if len(prices) == 1 else f"{f(prices[0])} – {f(prices[-1])}"


def to_editable(it, cur):
    """Fiche brute -> fiche en texte, modifiable dans l'aperçu."""
    compare = ""
    if it["compare"] and it["price"] and it["compare"] > it["price"][0]:
        compare = fmt_price([it["compare"]], cur)
    urls = it["image_urls"]
    return {
        "title": it["title"],
        "variant": it.get("variant") or "",
        "collection": it["collection"],
        "price": fmt_price(it["price"], cur),
        "compare": compare,
        "stock": it["stock"],
        "sizes": ", ".join(it["sizes"]),
        "img1": urls[0] if len(urls) > 0 else "",
        "img2": urls[1] if len(urls) > 1 else "",
        "gallery": it.get("gallery", urls),
        "note": it.get("photo_note") or "",
    }


# Nom affiché en haut du PDF pour les boutiques connues (sinon : déduit du nom de domaine)
SHOP_NAMES = {"kilometre.paris": "Kilometre Paris"}


def collect(url, img_idx=(0, 1), cur="€"):
    """Récupère la boutique et prépare les fiches modifiables (sans télécharger les photos)."""
    base, kind, handle = parse_url(url)
    products = fetch_products(base, kind, handle)
    coll = collection_title(base, kind, handle)
    items = [to_editable(it, cur) for p in products for it in normalise(p, coll, img_idx)]
    domain = urlparse(base).netloc.replace("www.", "")
    shop = SHOP_NAMES.get(domain, domain.split(".")[0].replace("-", " ").title())
    subtitle = f"Collection {coll}" if coll else ("Produit" if kind == "product" else "Tous les produits")
    return {"shop": shop, "subtitle": subtitle, "filename": f"{domain.split('.')[0]}_{handle or 'catalogue'}.pdf",
            "items": items}


def render_pdf(data, labels):
    """Télécharge les photos choisies et construit le PDF. Retourne un BytesIO.
    Seules les photos venant des galeries récupérées sont téléchargées (sécurité)."""
    items = data["items"]
    allowed = {u for it in items for u in it.get("gallery", [])}
    wanted = list({u for it in items for u in (it["img1"], it["img2"]) if u and u in allowed})
    with ThreadPoolExecutor(max_workers=8) as ex:
        bufs = dict(zip(wanted, ex.map(download_image, wanted)))
    for it in items:
        it["images"] = [bufs.get(it["img1"]), bufs.get(it["img2"])]
    return build_pdf(items, data["shop"], data["subtitle"], labels)


def _spaced(c, x, y, text, font, size, color, spacing=0.2, right=False):
    """Texte en majuscules espacées (style du site)."""
    text = text.upper()
    cs = size * spacing
    if right:
        x -= c.stringWidth(text, font, size) + cs * (len(text) - 1)
    c.setFont(font, size); c.setFillColor(color)
    c.drawString(x, y, text, charSpace=cs)


def build_pdf(items, shop_name, subtitle, labels):
    W, H = A4
    M = 36
    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=A4)
    c.setTitle(f"{shop_name} – {subtitle}")
    page = 0
    total_pages = (len(items) + 1) // 2

    def header():
        x = M
        if LOGO.exists():
            c.drawImage(str(LOGO), M, H - M - 46, 44, 46, mask="auto", preserveAspectRatio=True)
            x = M + 58
        _spaced(c, x, H - M - 18, shop_name[:40], F_BOLD, 15, RED, 0.2)
        c.setFont(F, 10.5); c.setFillColor(BLUE)
        c.drawString(x, H - M - 36, subtitle[:70])
        _spaced(c, W - M, H - M - 18, f"{len(items)} pièce(s)", F_MED, 8, BLUE_SOFT, 0.2, right=True)
        _spaced(c, W - M, H - M - 36, f"relevé du {datetime.date.today():%d/%m/%Y}", F, 8, BLUE_SOFT, 0.2, right=True)
        c.setStrokeColor(BLUE); c.setLineWidth(0.8); c.line(M, H - M - 54, W - M, H - M - 54)

    def footer():
        c.setFillColor(YELLOW); c.rect(0, 0, W, 26, stroke=0, fill=1)
        _spaced(c, M, 9.5, shop_name[:40], F_MED, 8, RED, 0.25)
        _spaced(c, W - M, 9.5, f"Page {page} / {total_pages}", F_MED, 8, RED, 0.25, right=True)

    def picture(buf, x, y, w, h, label):
        c.setFillColor(BG); c.rect(x, y, w, h, stroke=0, fill=1)
        if buf:
            buf.seek(0)
            img = ImageReader(buf); iw, ih = img.getSize()
            s = min(w / iw, h / ih); dw, dh = iw * s, ih * s
            c.drawImage(img, x + (w - dw) / 2, y + (h - dh) / 2, dw, dh)
        else:
            _spaced(c, x + w / 2 - 34, y + h / 2, "Pas de photo", F, 7.5, BLUE_SOFT, 0.15)
        _spaced(c, x, y - 12, label, F_MED, 7.5, BLUE_SOFT, 0.2)

    top = 0
    for i, it in enumerate(items):
        if i % 2 == 0:
            if i:
                c.showPage()
            page += 1
            header()
            footer()
            top = H - M - 62
        shift = 15 if it.get("variant") else 0
        c.setFont(F_MED, 15); c.setFillColor(BLUE)
        c.drawString(M, top - 18, it["title"][:70])
        if shift:
            _spaced(c, M, top - 34, it["variant"][:60], F_MED, 8.5, RED, 0.18)
        rows = [("Collection", it["collection"]), ("Prix", it["price"]), ("Quantité", it["stock"])]
        if it.get("sizes"):
            rows.append(("Tailles", it["sizes"]))
        yy = top - 42 - shift
        for k, v in rows:
            v = (v or "—")[:90]
            _spaced(c, M, yy + 1, k, F_MED, 7, BLUE_SOFT, 0.2)
            c.setFont(F_MED if k == "Prix" else F, 10.5); c.setFillColor(BLUE)
            c.drawString(M + 78, yy, v)
            if k == "Prix" and it.get("compare"):
                x = M + 78 + c.stringWidth(v, F_MED, 10.5) + 10
                old = it["compare"][:30]
                c.setFont(F, 9.5); c.setFillColor(SALE); c.drawString(x, yy, old)
                ow = c.stringWidth(old, F, 9.5)
                c.setStrokeColor(SALE); c.setLineWidth(0.7); c.line(x, yy + 3.3, x + ow, yy + 3.3)
                tx = x + ow + 8
                c.setFillColor(YELLOW); c.rect(tx, yy - 3, 40, 13, stroke=0, fill=1)
                _spaced(c, tx + 5, yy + 0.5, "Promo", F_BOLD, 6.5, BLUE, 0.2)
            yy -= 15
        iw, ih = (W - 2 * M - 12) / 2, 196
        iy = top - 340 + 24
        for k in range(2):
            picture(it["images"][k], M + k * (iw + 12), iy, iw, ih, labels[k])
        if it.get("note"):
            c.setFont(F_IT, 8); c.setFillColor(RED)
            c.drawRightString(W - M, iy - 12, it["note"][:60])
        if i % 2 == 0 and i + 1 < len(items):
            c.setStrokeColor(LINE); c.setLineWidth(0.6); c.line(M, top - 344, W - M, top - 344)
        top -= 362
    c.save()
    out.seek(0)
    return out
