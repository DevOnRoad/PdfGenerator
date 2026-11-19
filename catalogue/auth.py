"""
Mot de passe commun à toute l'équipe, pour la version en ligne.

- Si la variable APP_PASSWORD est définie (sur l'hébergeur), toutes les pages demandent
  ce mot de passe. On le change en modifiant la variable : tout le monde doit se reconnecter.
- Si elle n'est pas définie (sur ton ordinateur), l'outil reste accessible sans mot de passe.
"""
import hashlib
import hmac
import os
import time

from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

SESSION_FLAG = "team_ok"


def _password():
    return os.environ.get("APP_PASSWORD", "")


def _fingerprint(pw):
    # Empreinte du mot de passe gardée en session : changer APP_PASSWORD déconnecte tout le monde
    return hashlib.sha256(("catalogue-pdf:" + pw).encode()).hexdigest()[:16]


def is_protected():
    return bool(_password())


class TeamPasswordMiddleware:
    """Renvoie vers la page de connexion tant que le mot de passe n'a pas été donné."""
    OPEN_PATHS = ("/connexion/", "/static/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        pw = _password()
        if pw and not request.path.startswith(self.OPEN_PATHS):
            if request.session.get(SESSION_FLAG) != _fingerprint(pw):
                return redirect(f"{reverse('connexion')}?next={request.get_full_path()}")
        return self.get_response(request)


def connexion(request):
    pw = _password()
    if not pw:
        return redirect("index")
    nxt = request.POST.get("next") or request.GET.get("next") or reverse("index")
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()},
                                          require_https=request.is_secure()):
        nxt = reverse("index")
    error = None
    if request.method == "POST":
        given = request.POST.get("password", "")
        if hmac.compare_digest(given.encode(), pw.encode()):
            request.session.cycle_key()
            request.session[SESSION_FLAG] = _fingerprint(pw)
            return redirect(nxt)
        time.sleep(1)  # ralentit les essais au hasard
        error = "Mot de passe incorrect."
    return render(request, "catalogue/connexion.html", {"error": error, "next": nxt})


def deconnexion(request):
    if request.method == "POST":
        request.session.flush()
    return redirect("connexion" if is_protected() else "index")


def protection(request):
    """Variable de template : afficher le bouton « Se déconnecter » seulement en ligne."""
    return {"team_protected": is_protected()}
