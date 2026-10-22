"""
Application principale - Collecte Semantiweb (API Ratings & Reviews)
Point d'entrée avec navigation entre les modules
"""
import streamlit as st
from auth import exiger_mot_de_passe
from charte import appliquer_charte, bandeau, section

APPLI = "Consumer Voice · Collecte Semantiweb"

# Les modules (et donc le client API, qui lit le token dès son import) ne sont chargés qu'APRÈS le
# contrôle du mot de passe : voir _charger_modules(), appelée dans main() (spec accès, exigence S3).
modules_available = False
bulk_v2_available = False
bulk_v2_error = None


def _charger_modules():
    """Importe les modules de l'application. Appelée seulement une fois le mot de passe vérifié."""
    global initialize_session_state, display_quotas, display_export_journal
    global module1_explorer, module2_manual_export, module3_bulk_export, modules_available
    global module4_bulk_export_v2, bulk_v2_available, bulk_v2_error
    from utils import initialize_session_state, display_quotas, display_export_journal

    # Import des modules
    try:
        import module1_explorer
        import module2_manual_export
        import module3_bulk_export
        modules_available = True
    except ImportError as e:
        st.error(f"Modules introuvables : {e}. Vérifiez que tous les fichiers de l'application sont présents.",
                 icon=":material/error:")
        modules_available = False

    # Bulk Export V2 : chargé à part, pour qu'un problème de ce module n'empêche pas les autres de fonctionner.
    try:
        import module4_bulk_export_v2
        bulk_v2_available = True
    except Exception as e:
        bulk_v2_error = e
        bulk_v2_available = False


# Entrée du menu → (sous-titre du bandeau, icône Material). Le module 3 n'a pas de bandeau : son fichier
# ne doit pas être modifié et garde son propre titre (règle n°1 du CLAUDE.md).
ACCUEIL = "Accueil"
EXPLORATEUR = "Explorateur API"
EXPORT_MANUEL = "Export manuel"
EXPORT_SEGMENT = "Export par segment"           # module 3 (ancien « Export bulk »)
EXPORT_GRANDS_VOLUMES = "Export grands volumes"  # module 4 (« Bulk Export V2 » dans le code et la doc)
JOURNAL = "Journal des exports"
MODULES = {
    ACCUEIL: ("Explorer, exporter et suivre les avis de l'API Ratings & Reviews.", "home"),
    EXPLORATEUR: ("Filtrer, choisir les produits et estimer le volume avant un export.", "search"),
    EXPORT_MANUEL: ("Exporter les avis des produits sélectionnés, en aperçu ou en entier.", "checklist"),
    EXPORT_SEGMENT: (None, "inventory_2"),
    EXPORT_GRANDS_VOLUMES: ("Export traçable, reprenable et vérifiable, jusqu'à 500 000 mentions "
                            "(synchro mensuelle du marché).", "database"),
    JOURNAL: ("Historique des exports réalisés depuis cette application.", "history"),
}


def display_navigation():
    """Affiche la navigation principale entre les modules"""
    st.sidebar.header("Navigation", anchor=False)

    module_choice = st.sidebar.radio(
        "Choisissez un module",
        list(MODULES),
        format_func=lambda nom: f":material/{MODULES[nom][1]}: {nom}",
        help="Sélectionnez le module à utiliser"
    )

    return module_choice


def display_module_descriptions():
    """Affiche les descriptions des modules"""
    with section("Guide des modules", "Chaque entrée du menu, à quoi elle sert et quand l'utiliser."):
        col1, col2, col3 = st.columns(3)

        with col1:
            st.subheader(EXPLORATEUR, anchor=False)
            st.markdown("""
            Explorer et préparer votre sélection.
            - Filtres : dates, catégories, marques, pays, sources
            - Liste des produits par marque, avec le nombre d'avis
            - Sélection produit par produit et estimation du volume
            - Export de la configuration (JSON), réutilisable dans les autres modules

            **Idéal pour :** découvrir les données et choisir précisément.
            """)

        with col2:
            st.subheader(EXPORT_MANUEL, anchor=False)
            st.markdown("""
            Exporter les avis des produits sélectionnés.
            - Import de la configuration de l'Explorateur API
            - Mode aperçu (50 avis au plus) ou export complet
            - Formats CSV, Excel et plat

            **Idéal pour :** des analyses ciblées.
            """)

        with col3:
            st.subheader(EXPORT_SEGMENT, anchor=False)
            st.markdown("""
            Exporter tous les avis d'une catégorie, d'un segment ou de marques choisies.
            - Import de la configuration
            - Pas de sélection produit par produit
            - Analyses rapides intégrées

            **Idéal pour :** des analyses sectorielles et concurrentielles.
            """)

        col4, col5, _ = st.columns(3)

        with col4:
            st.subheader(EXPORT_GRANDS_VOLUMES, anchor=False)
            st.markdown("""
            Exporter de gros volumes, jusqu'à 500 000 mentions : la synchro mensuelle du marché.
            - Export page par page, enregistré au fil de l'eau
            - Arrêt et reprise au dernier point sûr
            - Contrôles qualité avant de déclarer l'export terminé
            - Fichiers téléchargeables et historique des exports

            **Idéal pour :** la synchro mensuelle du marché, qui doit être complète et vérifiée.
            """)

        with col5:
            st.subheader(JOURNAL, anchor=False)
            st.markdown("""
            Suivre les exports réalisés.
            - Historique des exports, filtrable par type, date et marque
            - Statistiques
            - Export du journal et nettoyage des anciennes lignes

            **Idéal pour :** le suivi et l'audit.
            """)


def display_workflow_guide():
    """Affiche le guide de workflow recommandé"""
    with section("Parcours recommandé", "Commencez toujours par l'Explorateur API, puis choisissez le type d'export."):
        st.markdown(f"""
        1. **Explorer** ({EXPLORATEUR}) : définissez vos filtres, choisissez les produits, estimez le volume,
           puis exportez la configuration JSON.
        2. **Exporter**, selon le besoin :
           - **{EXPORT_MANUEL}** : importez la configuration, testez avec un aperçu, puis lancez l'export complet ;
           - **{EXPORT_SEGMENT}** : importez la configuration et exportez tous les avis d'une catégorie,
             d'un segment ou des marques choisies ;
           - **{EXPORT_GRANDS_VOLUMES}** : la synchro mensuelle du marché, avec reprise après arrêt et contrôles qualité.
        3. **Suivre** ({JOURNAL}) : retrouvez l'historique de vos exports.

        Conseils : utilisez les aperçus avant les exports complets, sauvegardez vos configurations
        et surveillez les quotas API.
        """)


def display_quotas_overview():
    """Affiche un aperçu des quotas API"""
    with st.expander("Quotas API", expanded=False, icon=":material/data_usage:"):
        display_quotas()


def main():
    """Application principale avec navigation entre modules"""
    # Configuration de la page
    st.set_page_config(
        page_title="Collecte Semantiweb",
        page_icon=":material/travel_explore:",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    # Accès par mot de passe : TOUJOURS en premier (rien ne s'exécute avant).
    exiger_mot_de_passe()
    appliquer_charte()
    _charger_modules()

    # Initialisation
    initialize_session_state()

    if not modules_available:
        bandeau(APPLI, "Application indisponible")
        st.error("Impossible de charger les modules : vérifiez que tous les fichiers de l'application sont "
                 "présents, puis rechargez la page.", icon=":material/error:")
        return

    module_choice = display_navigation()

    # Titre de la page : le bandeau, sauf pour le module 3 qui garde son propre titre.
    sous_titre = MODULES[module_choice][0]
    if module_choice != EXPORT_SEGMENT:
        bandeau(APPLI, module_choice, sous_titre=sous_titre)

    # Affichage des quotas en tête
    display_quotas_overview()

    # Routage vers les modules
    if module_choice == EXPLORATEUR:
        module1_explorer.main()

    elif module_choice == EXPORT_MANUEL:
        module2_manual_export.main()

    elif module_choice == EXPORT_SEGMENT:
        module3_bulk_export.main()

    elif module_choice == EXPORT_GRANDS_VOLUMES:
        if bulk_v2_available:
            module4_bulk_export_v2.main()
        else:
            st.error(f"{EXPORT_GRANDS_VOLUMES} indisponible ({type(bulk_v2_error).__name__}). Les autres modules "
                     "fonctionnent ; vérifiez l'installation de l'application, puis rechargez la page.",
                     icon=":material/error:")

    elif module_choice == JOURNAL:
        display_export_journal()

    # Page d'accueil
    else:
        display_module_descriptions()
        display_workflow_guide()


if __name__ == "__main__":
    main()
