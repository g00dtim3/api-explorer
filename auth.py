"""
Accès par mot de passe (spec « Accès par mot de passe (Streamlit) » du 15/10/2026).

À appeler EN PREMIER sur chaque page, juste après ``st.set_page_config`` : tant que le bon mot de passe
n'a pas été saisi, la page s'arrête (``st.stop()``) avant tout appel API ou connexion à la base (S3).

Le mot de passe se règle dans les Secrets de Streamlit : ``APP_PASSWORD = "..."`` (jamais dans le code, S1).
"""

import hmac
import time

import streamlit as st

MAX_ESSAIS = 5           # S5 : nombre d'échecs avant blocage
BLOCAGE_SECONDES = 300   # S5 : durée du blocage (5 minutes)
LONGUEUR_MIN = 16        # S7 : longueur minimale du mot de passe configuré


def _mot_de_passe_attendu() -> str:
    """Lit le mot de passe dans les Secrets. Absent ou vide : accès refusé (S6).
    Trop court : accès refusé aussi (S7), pour ne jamais fonctionner avec un mot de passe faible."""
    try:
        attendu = str(st.secrets["APP_PASSWORD"])
    except Exception:
        attendu = ""
    if not attendu:
        st.error("Configuration manquante : accès impossible.")
        st.stop()
    if len(attendu) < LONGUEUR_MIN:
        st.error(f"Configuration invalide : le mot de passe configuré doit faire au moins {LONGUEUR_MIN} caractères. "
                 "Accès impossible.")
        st.stop()
    try:  # le mot de passe ne doit jamais apparaître dans un message ou un journal
        from bulk_export.logging_utils import register_secret
        register_secret(attendu)
    except Exception:
        pass
    return attendu


def _verifier() -> None:
    """Appelée quand on clique sur « Entrer »."""
    saisi = st.session_state.pop("mot_de_passe_saisi", "") or ""  # S4 : effacé aussitôt
    attendu = _mot_de_passe_attendu()
    if hmac.compare_digest(saisi.encode("utf-8"), attendu.encode("utf-8")):  # S2
        st.session_state["authentifie"] = True
        st.session_state["echecs"] = 0
    else:
        echecs = st.session_state.get("echecs", 0) + 1
        st.session_state["echecs"] = echecs
        if echecs >= MAX_ESSAIS:
            st.session_state["bloque_jusqua"] = time.time() + BLOCAGE_SECONDES
            st.session_state["echecs"] = 0


def exiger_mot_de_passe() -> None:
    """Arrête la page tant que le bon mot de passe n'a pas été saisi."""
    # Secret absent, vide ou trop court : on refuse même une session déjà connectée (S6, S7).
    _mot_de_passe_attendu()

    # Déjà connecté : bouton de déconnexion (F4), puis on laisse passer.
    if st.session_state.get("authentifie"):
        if st.sidebar.button("Se déconnecter", key="auth_deconnexion"):
            st.session_state.clear()
            st.rerun()
        return

    # Bloqué après trop d'essais (S5).
    if time.time() < st.session_state.get("bloque_jusqua", 0):
        st.error("Trop d'essais. Réessayez dans quelques minutes.")
        st.stop()

    # Écran de connexion (F1) : un champ masqué et un bouton, rien d'autre.
    st.title("Accès protégé")
    with st.form("connexion"):
        st.text_input("Mot de passe", type="password", key="mot_de_passe_saisi")
        st.form_submit_button("Entrer", on_click=_verifier)
    if st.session_state.get("echecs"):
        st.error("Mot de passe incorrect.")  # F3
    st.stop()  # S3 : rien après cette ligne ne s'exécute
