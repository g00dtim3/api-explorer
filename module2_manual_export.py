"""
Module 2 - Export Manuel de Sélection
Permet d'exporter une sélection manuelle de produits
"""
import streamlit as st
import pandas as pd
import io
import json
import time
from api_client import api_client
from utils import (
    initialize_session_state,
    build_filter_params,
    load_configuration_from_json,
    export_configuration_to_json,
    generate_export_filename,
    postprocess_reviews,
    display_quotas,
    log_export_activity,
    create_excel_download,
    display_download_buttons,
    display_excel_warning,
    format_nombre
)
from charte import section, vide

# Mode d'export (libellés affichés ET valeurs comparées dans le code)
MODE_APERCU = "Aperçu (50 avis au plus)"
MODE_COMPLET = "Export complet"


def display_configuration_interface():
    """Interface de chargement de configuration"""
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown("#### Charger une configuration existante")
        json_input = st.text_area(
            "Collez votre configuration JSON ici",
            height=200,
            help="Configuration générée par l'Explorateur API"
        )
        
        if st.button("Charger la configuration", type="primary", icon=":material/upload_file:"):
            if load_configuration_from_json(json_input):
                st.success("Configuration chargée.", icon=":material/check_circle:")
                st.rerun()
    
    with col2:
        st.markdown("#### Configuration actuelle")
        if st.session_state.get("filters"):
            filters = st.session_state.filters
            selected_products = st.session_state.get("selected_product_ids", [])
            
            st.metric("Marques", len(filters.get("brand", [])), border=True)
            st.metric("Produits sélectionnés", len(selected_products), border=True)
            st.metric("Période", f"{filters.get('start_date')} → {filters.get('end_date')}", border=True)
            
            if st.button("Effacer la configuration", icon=":material/delete:"):
                st.session_state.filters = {}
                st.session_state.selected_product_ids = []
                st.session_state.apply_filters = False
                st.rerun()
        else:
            vide("Aucune configuration chargée. Collez celle de l'Explorateur API, puis chargez-la.")


def display_configuration_summary():
    """Affiche le résumé de la configuration chargée"""
    if not st.session_state.get("filters"):
        return
    
    filters = st.session_state.filters
    selected_products = st.session_state.get("selected_product_ids", [])
    
    # Résumé des filtres
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### Filtres")
        st.markdown(f"**Période :** `{filters['start_date']}` → `{filters['end_date']}`")
        st.markdown(f"**Catégorie :** `{filters.get('category', 'ALL')}`")
        st.markdown(f"**Sous-catégorie :** `{filters.get('subcategory', 'ALL')}`")
        st.markdown(f"**Marques :** `{', '.join(filters.get('brand', []))}`")
    
    with col2:
        st.markdown("#### Sélection")
        st.markdown(f"**Produits sélectionnés :** `{len(selected_products)}`")
        
        if selected_products:
            # Afficher quelques produits en exemple
            preview_products = selected_products[:5]
            products_text = ", ".join(f"`{p}`" for p in preview_products)
            if len(selected_products) > 5:
                products_text += f" ... (+{len(selected_products) - 5} autres)"
            st.markdown(f"**Exemples :** {products_text}")
    
    # Estimation du volume
    if selected_products:
        display_volume_estimation()


def display_volume_estimation():
    """Estime le volume total de reviews pour la sélection"""
    selected_products = st.session_state.get("selected_product_ids", [])
    filters = st.session_state.filters
    
    if not selected_products:
        return
    
    st.markdown("#### Estimation du volume")
    
    if st.button("Calculer le volume total", key="estimate_volume", icon=":material/calculate:"):
        with st.spinner("Calcul du volume..."):
            # Paramètres de base
            base_params = build_filter_params(filters)
            base_params["product"] = ",".join(selected_products)
            
            try:
                # Appel API pour obtenir les métriques globales
                metrics = api_client.get_metrics(**base_params)
                if metrics:
                    total_reviews = metrics.get("nbDocs", 0)
                    
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Volume total estimé", f"{format_nombre(total_reviews)} avis", border=True)
                    with col2:
                        st.metric("Produits", len(selected_products), border=True)
                    with col3:
                        avg_per_product = total_reviews / len(selected_products) if selected_products else 0
                        st.metric("Moyenne par produit", f"{format_nombre(round(avg_per_product))} avis", border=True)
                    
                    # Stocker pour l'interface d'export
                    st.session_state.estimated_volume = total_reviews
                else:
                    st.error("Volume indisponible : l'API n'a pas renvoyé de métriques. Réessayez dans un instant.", icon=":material/error:")
            except Exception as e:
                st.error(f"Calcul impossible : {e}. Réessayez dans un instant.", icon=":material/error:")


def display_export_interface():
    """Interface principale d'export"""
    if not st.session_state.get("selected_product_ids"):
        st.warning("Aucun produit sélectionné : chargez d'abord une configuration qui contient des produits.", icon=":material/warning:")
        return
    
    # Options d'export
    st.markdown("#### Options d'export")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("##### Pagination")
        rows_per_page = st.number_input(
            "Reviews par page",
            min_value=10,
            max_value=1000,
            value=100,
            step=10,
            help="Plus élevé = moins d'appels API mais plus de mémoire"
        )
        
        use_random = st.checkbox("Randomiser les résultats")
        if use_random:
            random_seed = st.number_input(
                "Seed aléatoire",
                min_value=1,
                max_value=9999,
                value=42
            )
        else:
            random_seed = None
    
    with col2:
        st.markdown("##### Mode d'export")
        export_mode = st.radio(
            "Type d'export",
            [MODE_APERCU, MODE_COMPLET],
            help="L'aperçu permet de tester rapidement"
        )
        
        is_preview = export_mode == MODE_APERCU
        
        # Affichage de l'estimation
        estimated_volume = st.session_state.get("estimated_volume", "?")
        if is_preview:
            export_volume = min(50, estimated_volume) if isinstance(estimated_volume, int) else 50
            st.info(f"Export prévu : {format_nombre(export_volume)} avis", icon=":material/info:")
        else:
            st.info(f"Export prévu : {format_nombre(estimated_volume)} avis", icon=":material/info:")
    
    # Bouton de lancement
    if st.button("Lancer l'export", type="primary", key="launch_manual_export", icon=":material/play_arrow:"):
        execute_manual_export(rows_per_page, use_random, random_seed, is_preview)


def execute_manual_export(rows_per_page, use_random, random_seed, is_preview):
    """Exécute l'export manuel"""
    
    # Vérification anti-double-export
    if st.session_state.get('export_in_progress', False):
        st.warning("Un export est déjà en cours : attendez qu'il se termine.", icon=":material/warning:")
        return
    
    # Marquer l'export comme en cours
    st.session_state.export_in_progress = True
    
    try:
        filters = st.session_state.filters
        selected_products = st.session_state.selected_product_ids
        
        # Construction des paramètres
        export_params = build_filter_params(filters, include_product_list=True)
        export_params["rows"] = min(rows_per_page, 50) if is_preview else rows_per_page
        
        if use_random and random_seed:
            export_params["random"] = str(random_seed)
        
        # Obtenir le volume total
        metrics = api_client.get_metrics(**build_filter_params(filters, include_product_list=True))
        total_available = metrics.get("nbDocs", 0) if metrics else 0
        
        if total_available == 0:
            st.warning("Aucun avis disponible pour cette sélection : élargissez la période ou les produits.", icon=":material/warning:")
            return
        
        # Configuration selon le mode
        if is_preview:
            max_reviews = min(50, total_available)
            st.info(f"Mode aperçu : chargement de {max_reviews} avis au plus.", icon=":material/info:")
        else:
            st.info(f"Export complet : {format_nombre(total_available)} avis…", icon=":material/info:")
            
        # Interface de progression
        status_text = st.empty()
        progress_bar = None if is_preview else st.progress(0)
        
        # Variables de pagination
        cursor_mark = "*"  # Le premier cursor est toujours "*"
        page_count = 0
        all_docs = []
        max_iterations = 1000 if not is_preview else 10
        
        # Détails de pagination : repliés, pour ne pas encombrer l'écran
        details = st.expander("Détails techniques de la pagination", icon=":material/code:")
        details.write(f"Démarrage avec cursor='*', rows={export_params['rows']}")
        
        # Boucle d'export
        while page_count < max_iterations:
            page_count += 1
            
            current_count = len(all_docs)
            status_text.text(f"Page {page_count} | récupérés : {format_nombre(current_count)} / {format_nombre(total_available)} avis")
            
            # CORRECTION PRINCIPALE: Utiliser "nextCursorMark" au lieu de "cursorMark"
            current_params = export_params.copy()
            current_params["nextCursorMark"] = cursor_mark  # CORRECTION
            
            # Debug des paramètres
            if page_count <= 3:
                details.write(f"Page {page_count}: nextCursorMark='{cursor_mark}', rows={current_params['rows']}")
            
            # Appel API
            result = api_client.get_reviews(**current_params)
            
            if not result or not result.get("docs"):
                st.warning(f"Pas de données à la page {page_count}.", icon=":material/warning:")
                break
            
            docs = result.get("docs", [])
            
            # Ajouter les reviews
            all_docs.extend(docs)
            
            details.write(f"Page {page_count}: +{len(docs)} reçus (total : {len(all_docs)})")
            
            # Mise à jour progression
            if progress_bar is not None:
                progress_percent = min(len(all_docs) / total_available, 1.0)
                progress_bar.progress(progress_percent)
            
            # Gestion du cursor
            next_cursor = result.get("nextCursorMark")
            
            # Debug du cursor
            if page_count <= 3:
                details.write(f"Cursor reçu: '{next_cursor}'")
                details.write(f"Cursor actuel: '{cursor_mark}'")
                details.write(f"Cursor identique: {next_cursor == cursor_mark}")
            
            # CONDITIONS D'ARRÊT
            if not next_cursor:
                details.write("Fin : pas de nextCursorMark")
                break
                
            if next_cursor == cursor_mark:
                details.write(f"Fin : cursor identique ('{cursor_mark}')")
                break
            
            # MISE À JOUR DU CURSOR
            cursor_mark = next_cursor
            
            # Conditions d'arrêt supplémentaires
            if len(all_docs) >= total_available:
                st.info(f"Tous les avis sont récupérés ({format_nombre(len(all_docs))}).", icon=":material/info:")
                break
            
            # En mode aperçu, on s'arrête après avoir assez de reviews
            if is_preview and len(all_docs) >= 50:
                st.info("Limite de l'aperçu atteinte.", icon=":material/info:")
                break
            
            # Pause entre requêtes
            if page_count % 5 == 0:
                time.sleep(0.1)
        
        # Diagnostic final
        details.write(f"Diagnostic final : {len(all_docs)} avis récupérés sur {total_available} attendus")
        
        # Vérifier les doublons après coup
        if all_docs:
            unique_ids = {doc.get('id') for doc in all_docs if doc.get('id')}
            if len(unique_ids) < len(all_docs):
                duplicates = len(all_docs) - len(unique_ids)
                st.warning(f"{duplicates} doublons détectés dans le résultat final.", icon=":material/warning:")
        
        # Stocker les résultats
        st.session_state.all_docs = all_docs
        st.session_state.export_params = export_params
        st.session_state.is_preview_mode = is_preview
        
        # Messages finaux
        mode_text = "aperçu manuel" if is_preview else "export manuel complet"
        if all_docs:
            status_text.text(f"{mode_text.capitalize()} terminé : {format_nombre(len(all_docs))} avis récupérés.")
            
            # Log de l'activité
            if not is_preview:
                log_export_activity(export_params, len(all_docs), "MANUAL_SELECTION")
            
            st.balloons()
        else:
            status_text.text("Aucun avis récupéré.")
    
    except Exception as e:
        st.error(f"Export interrompu : {str(e)}. Relancez l'export ; si l'erreur revient, essayez l'aperçu.", icon=":material/error:")
    
    finally:
        # Toujours libérer le verrou
        st.session_state.export_in_progress = False


def display_export_results():
    """Affiche les résultats de l'export"""
    if not st.session_state.get("all_docs"):
        return
    
    docs = st.session_state.all_docs
    total_results = len(docs)
    is_preview = st.session_state.get("is_preview_mode", False)
    
    # Bandeau d'information
    if is_preview:
        st.info("Mode aperçu : échantillon limité des données.", icon=":material/info:")
    else:
        st.success(f"Export complet : {format_nombre(total_results)} avis récupérés.", icon=":material/check_circle:")
    
    # Pagination pour l'affichage
    rows_per_page = 100
    total_pages = max(1, (total_results + rows_per_page - 1) // rows_per_page)
    
    # Contrôles de pagination
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col1:
        if st.button("Page précédente", icon=":material/chevron_left:", disabled=st.session_state.get("current_page", 1) <= 1):
            st.session_state.current_page = max(1, st.session_state.get("current_page", 1) - 1)
            st.rerun()
    
    with col2:
        current_page = st.selectbox(
            "Page",
            range(1, total_pages + 1),
            index=st.session_state.get("current_page", 1) - 1,
            key="page_selector"
        )
        st.session_state.current_page = current_page
    
    with col3:
        if st.button("Page suivante", icon=":material/chevron_right:", disabled=st.session_state.get("current_page", 1) >= total_pages):
            st.session_state.current_page = min(total_pages, st.session_state.get("current_page", 1) + 1)
            st.rerun()
    
    # Affichage des données de la page courante
    start_idx = (current_page - 1) * rows_per_page
    end_idx = min(start_idx + rows_per_page, total_results)
    page_docs = docs[start_idx:end_idx]
    
    st.caption(f"Avis {start_idx + 1} à {end_idx} sur {format_nombre(total_results)}")
    
    # Créer le DataFrame
    df_page = pd.json_normalize(page_docs)
    df_page = df_page.applymap(lambda x: str(x) if isinstance(x, (dict, list)) else x)
    
    # Afficher le tableau
    st.dataframe(df_page, use_container_width=True)
    
    # Boutons de téléchargement
    display_download_interface(docs, df_page, current_page)


def display_download_interface(all_docs, df_page, current_page):
    """Interface de téléchargement des résultats"""
    is_preview = st.session_state.get("is_preview_mode", False)
    
    st.markdown("#### Téléchargements")
    
    # Avertissement Excel si nécessaire
    display_excel_warning()
    
    # Téléchargement de la page courante
    st.markdown("##### Page courante")
    
    page_filename_base = f"reviews_manuel_page{current_page}"
    display_download_buttons(df_page, page_filename_base, mode="page", page=current_page)
    
    # Téléchargement complet
    st.markdown("##### Export complet")
    
    # Préparer les données complètes
    df_full = pd.json_normalize(all_docs)
    df_full = df_full.applymap(lambda x: str(x) if isinstance(x, (dict, list)) else x)
    
    full_filename_base = f"reviews_manuel_{'apercu' if is_preview else 'complet'}"
    display_download_buttons(df_full, full_filename_base, mode="complet")


def display_current_configuration_export():
    """Affiche la configuration actuelle pour export"""
    if not st.session_state.get("filters"):
        return
    
    export_config = export_configuration_to_json(
        st.session_state.filters,
        st.session_state.get("selected_product_ids", [])
    )
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown("Configuration JSON réutilisable :")
        st.code(json.dumps(export_config, indent=2), language="json")
    
    with col2:
        # Bouton de téléchargement
        config_json = json.dumps(export_config, indent=2)
        st.download_button(
            "Télécharger la configuration",
            config_json,
            file_name="config_export_manuel.json",
            mime="application/json",
            icon=":material/download:"
        )


def main():
    """Interface principale du module export manuel"""
    initialize_session_state()

    # Interface de configuration
    with section("Configuration d'export", "Collez la configuration créée avec l'Explorateur API."):
        display_configuration_interface()

    # Si configuration chargée
    if st.session_state.get("apply_filters") and st.session_state.get("filters"):
        with section("Configuration chargée"):
            display_configuration_summary()

        with section("Export des avis", "Testez d'abord avec l'aperçu, puis lancez l'export complet."):
            display_export_interface()

        if st.session_state.get("all_docs"):
            with section("Résultats de l'export"):
                display_export_results()

        with section("Configuration actuelle", "Configuration JSON réutilisable dans les autres modules."):
            display_current_configuration_export()

    else:
        with section("Comment utiliser l'Export manuel",
                     "Exportez précisément les avis d'une sélection de produits."):
            st.markdown("""
            1. **Chargez une configuration** créée avec l'Explorateur API
            2. **Vérifiez** les filtres et produits sélectionnés
            3. **Estimez le volume** total d'avis
            4. **Lancez l'export** en mode aperçu ou complet
            5. **Téléchargez** les résultats : CSV, Excel ou format plat

            Conseils : testez d'abord avec l'aperçu (50 avis au plus) ; l'export complet peut prendre du temps
            selon le volume ; les configurations sont réutilisables d'une session à l'autre.
            """)


if __name__ == "__main__":
    main()
