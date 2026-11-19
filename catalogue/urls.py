from django.urls import path

from . import auth, views

urlpatterns = [
    path("", views.index, name="index"),
    path("apercu/", views.apercu, name="apercu"),
    path("connexion/", auth.connexion, name="connexion"),
    path("deconnexion/", auth.deconnexion, name="deconnexion"),
]
