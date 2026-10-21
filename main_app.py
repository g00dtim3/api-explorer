"""
Application principale - Explorateur API Ratings & Reviews
Point d'entrée avec navigation entre les 3 modules
"""
import streamlit as st
from auth import exiger_mot_de_passe

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
        st.error(f"❌ Erreur d'import des modules : {e}")
        modules_available = False

    # Bulk Export V2 : chargé à part, pour qu'un problème de ce module n'empêche pas les autres de fonctionner.
    try:
        import module4_bulk_export_v2
        bulk_v2_available = True
    except Exception as e:
        bulk_v2_error = e
        bulk_v2_available = False


def display_navigation():
    """Affiche la navigation principale entre les modules"""
    st.sidebar.title("🧭 Navigation")
    
    # Sélection du module
    module_choice = st.sidebar.radio(
        "Choisissez un module",
        [
            "🔍 Module 1 - Explorateur API",
            "🎯 Module 2 - Export Manuel", 
            "🚀 Module 3 - Export Bulk",
            "🧱 Bulk Export V2",
            "📋 Journal des exports"
        ],
        help="Sélectionnez le module à utiliser"
    )
    
    return module_choice


def display_module_descriptions():
    """Affiche les descriptions détaillées des modules"""
    st.header("📚 Guide des modules")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown("""
        ### 🔍 Module 1 - Explorateur API
        
        **Objectif :** Explorer et préparer votre sélection
        
        **Fonctionnalités :**
        - 🔍 Filtrage avancé (dates, catégories, marques...)
        - 📦 Liste des produits par marque
        - 📊 Compteurs d'avis optionnels
        - 🎯 Sélection produit par produit
        - 📈 Estimation du volume total
        - 💾 Export de configuration réutilisable
        
        **Idéal pour :** Découverte et sélection précise
        """)
    
    with col2:
        st.markdown("""
        ### 🎯 Module 2 - Export Manuel
        
        **Objectif :** Export précis de produits sélectionnés
        
        **Fonctionnalités :**
        - 📥 Import de configuration (Module 1)
        - 🎯 Export des produits sélectionnés uniquement
        - 🔍 Modes aperçu et complet
        - 📄 Formats multiples (CSV, Excel, Plat)
        - 📊 Pagination des résultats
        - 💾 Configuration réutilisable
        
        **Idéal pour :** Analyses ciblées et précises
        """)
    
    with col3:
        st.markdown("""
        ### 🚀 Module 3 - Export Bulk
        
        **Objectif :** Export massif par marque
        
        **Fonctionnalités :**
        - 📥 Import de configuration
        - 🚀 Export de toutes les reviews des marques
        - 📊 Pas de sélection produit individuelle
        - 📈 Analyses rapides intégrées
        - 💾 Optimisé pour gros volumes
        - 🔍 Mode aperçu bulk disponible
        
        **Idéal pour :** Analyses sectorielles et concurrentielles
        """)
    
    with col4:
        st.markdown("""
        ### 📋 Journal des exports
        
        **Objectif :** Suivi et historique des activités
        
        **Fonctionnalités :**
        - 📊 Historique complet des exports
        - 🔍 Filtrage par type, date, marque
        - 📈 Statistiques et analyses
        - 💾 Export du journal
        - 🗑️ Nettoyage automatique
        - 📋 Audit des activités
        
        **Idéal pour :** Monitoring et audit
        """)
    


def display_workflow_guide():
    """Affiche le guide de workflow recommandé"""
    st.markdown("---")
    st.header("🔄 Workflow recommandé")
    
    st.markdown("""
    ### 📋 Processus étape par étape :
    
    #### 1️⃣ **Exploration** (Module 1)
    - Définissez vos filtres (dates, catégories, marques)
    - Explorez les produits disponibles
    - Sélectionnez précisément les produits d'intérêt
    - Estimez le volume de données  
    - Exportez la configuration JSON
    
    #### 2️⃣ **Export ciblé** (Module 2) 
    - Importez votre configuration du Module 1
    - Testez avec un aperçu (50 reviews max)
    - Lancez l'export complet si satisfait
    - Téléchargez dans le format souhaité
    
    #### 🔀 **Ou Export massif** (Module 3)
    - Importez votre configuration 
    - Estimez le volume total par marque
    - Lancez l'export bulk (toutes les reviews)
    - Analysez les données avec les outils intégrés
    
    ### 💡 **Conseils d'utilisation :**
    - **Commencez toujours par le Module 1** pour explorer
    - **Utilisez les aperçus** avant les exports complets
    - **Sauvegardez vos configurations** pour réutilisation
    - **Surveillez vos quotas API** dans chaque module
    - **Le Module 3 est idéal** pour les analyses sectorielles
    """)


def display_quotas_overview():
    """Affiche un aperçu des quotas API"""
    with st.expander("📊 Quotas API globaux", expanded=False):
        display_quotas()


def main():
    """Application principale avec navigation entre modules"""
    # Configuration de la page
    st.set_page_config(
        page_title="Explorateur API Ratings & Reviews", 
        layout="wide",
        initial_sidebar_state="expanded"
    )

    # Accès par mot de passe : TOUJOURS en premier (rien ne s'exécute avant).
    exiger_mot_de_passe()
    _charger_modules()
    
    # Initialisation
    initialize_session_state()
    
    # Titre principal
    st.title("🔍 Explorateur API Ratings & Reviews")
    st.markdown("**Suite complète d'exploration et d'export de données reviews**")
    
    # Affichage des quotas en header
    display_quotas_overview()
    
    # Navigation
    if not modules_available:
        st.error("❌ Impossible de charger les modules. Vérifiez que tous les fichiers sont présents.")
        return
    
    module_choice = display_navigation()
    
    # Routage vers les modules
    if "Module 1" in module_choice:
        st.markdown("---")
        module1_explorer.main()
        
    elif "Module 2" in module_choice:
        st.markdown("---")
        module2_manual_export.main()
        
    elif "Module 3" in module_choice:
        st.markdown("---")
        module3_bulk_export.main()
        
    elif "Bulk Export V2" in module_choice:
        st.markdown("---")
        if bulk_v2_available:
            module4_bulk_export_v2.main()
        else:
            st.error(f"❌ Bulk Export V2 indisponible : {type(bulk_v2_error).__name__}")

    elif "Journal des exports" in module_choice:
        st.markdown("---")
        display_export_journal()
    
    # Page d'accueil si aucun module spécifique
    else:
        # Affichage des descriptions de modules
        display_module_descriptions()
        
        # Guide de workflow
        display_workflow_guide()
        
        # Informations supplémentaires
        st.markdown("---")
        st.markdown("""
        ### 🛠️ Informations techniques
        
        **Architecture modulaire :**
        - `api_client.py` : Client API partagé avec cache
        - `utils.py` : Utilitaires et fonctions communes  
        - `module1_explorer.py` : Module d'exploration
        - `module2_manual_export.py` : Module d'export manuel
        - `module3_bulk_export.py` : Module d'export bulk
        - `main_app.py` : Application principale
        
        **Fonctionnalités transversales :**
        - ✅ Cache API intégré (1h TTL)
        - ✅ Gestion d'état Streamlit optimisée
        - ✅ Export multi-formats automatique
        - ✅ Pagination intelligente
        - ✅ Logging des activités d'export
        - ✅ Protection anti-double-export
        
        **Configuration requise :**
        - Token API dans `st.secrets["api"]["token"]`
        - Python packages : `streamlit`, `pandas`, `requests`
        """)


if __name__ == "__main__":
    main()
