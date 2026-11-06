from django.http import FileResponse
from django.shortcuts import redirect, render

from .forms import CatalogueForm
from .services import ShopError, collect, render_pdf

SESSION_KEY = "catalogue"
FIELDS = ("title", "variant", "collection", "price", "compare", "stock", "sizes", "img1", "img2", "note")


def index(request):
    """Étape 1 : on colle le lien, on récupère les produits, puis on passe à l'aperçu."""
    form = CatalogueForm(request.POST or None)
    error = None

    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            data = collect(d["url"], img_idx=(d["img1"] - 1, d["img2"] - 1), cur=d["cur"])
            data["labels"] = [d["lab1"], d["lab2"]]
            request.session[SESSION_KEY] = data
            return redirect("apercu")
        except ShopError as e:
            error = str(e)
        except Exception as e:  # erreur imprévue : on l'affiche plutôt que planter
            error = f"Erreur inattendue : {e}"

    return render(request, "catalogue/index.html", {"form": form, "error": error})


def apercu(request):
    """Étape 2 : aperçu modifiable. En POST, on enregistre les modifications et on renvoie le PDF."""
    data = request.session.get(SESSION_KEY)
    if not data:
        return redirect("index")

    if request.method == "POST":
        p = request.POST
        originals = data["items"]

        order = [int(x) for x in p.get("order", "").split(",") if x.strip().isdigit()]
        if not p.get("order_sent"):  # navigateur sans JavaScript : on garde tout, dans l'ordre
            order = list(range(len(originals)))
        order = [i for i in order if 0 <= i < len(originals)]

        items = []
        for i in order:
            it = dict(originals[i])
            for f in FIELDS:
                key = f"{i}-{f}"
                if key in p:
                    it[f] = p[key].strip()
            items.append(it)

        # On garde les modifications en session : retour à l'aperçu = on retrouve son travail
        data["shop"] = p.get("shop", data["shop"]).strip() or data["shop"]
        data["subtitle"] = p.get("subtitle", data["subtitle"]).strip()
        data["labels"] = [p.get("lab1", "").strip() or "Photo 1", p.get("lab2", "").strip() or "Photo 2"]
        for i in range(len(originals)):
            for f in FIELDS:
                if f"{i}-{f}" in p:
                    originals[i][f] = p[f"{i}-{f}"].strip()
        request.session[SESSION_KEY] = data

        if not items:
            return render(request, "catalogue/apercu.html",
                          {"data": data, "error": "Garde au moins une fiche pour générer le PDF."})

        pdf = render_pdf({**data, "items": items}, data["labels"])
        return FileResponse(pdf, as_attachment=True, filename=data["filename"],
                            content_type="application/pdf")

    return render(request, "catalogue/apercu.html", {"data": data, "error": None})
