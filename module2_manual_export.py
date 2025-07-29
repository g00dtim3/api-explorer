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
    display_excel_warning
)


def display_configuration_interface():
    """Interface de chargement de configuration"""
    st.header("📥 Configuration d'export")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown("### 📎 Charger une configuration existante")
        json_input = st.text_area(
            "Collez votre configuration JSON ici",
            height=200,
            help="Configuration générée par le Module 1 - Explorateur"
        )
        
        if st.button("🔄 Charger la configuration", type="primary"):
            if load_configuration_from_json(json_input):
                st.success("Configuration chargée avec succès !")
                st.rerun()
    
    with col2:
        st.markdown("### 📋 Configuration actuelle")
        if st.session_state.get("filters"):
            filters = st.session_state.filters
            selected_products = st.session_state.get("selected_product_ids", [])
            
            st.metric("Marques", len(filters.get("brand", [])))
            st.metric("Produits sélectionnés", len(selected_products))
            st.metric("Période", f"{filters.get('start_date')} → {filters.get('end_date')}")
            
            if st.button("🗑️ Effacer la configuration"):
                st.session_state.filters = {}
                st.session_state.selected_product_ids = []
                st.session_state.apply_filters = False
                st.rerun()
        else:
            st.info("Aucune configuration chargée")


def display_configuration_summary():
    """Affiche le résumé de la configuration chargée"""
    if not st.session_state.get("filters"):
        return
    
    filters = st.session_state.filters
    selected_products = st.session_state.get("selected_product_ids", [])
    
    st.markdown("---")
    st.header("📋 Configuration chargée")
    
    # Résumé des filtres
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 🔍 Filtres")
        st.markdown(f"**📅 Période :** `{filters['start_date']}` → `{filters['end_date']}`")
        st.markdown(f"**🏷️ Catégorie :** `{filters.get('category', 'ALL')}`")
        st.markdown(f"**🏷️ Sous-catégorie :** `{filters.get('subcategory', 'ALL')}`")
        st.markdown(f"**🏢 Marques :** `{', '.join(filters.get('brand', []))}`")
    
    with col2:
        st.markdown("### 🎯 Sélection")
        st.markdown(f"**📦 Produits sélectionnés :** `{len(selected_products)}`")
        
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
    
    st.markdown("### 📊 Estimation du volume")
    
    if st.button("📈 Calculer le volume total", key="estimate_volume"):
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
                        st.metric("📊 Volume total estimé", f"{total_reviews:,} reviews")
                    with col2:
                        st.metric("📦 Produits", len(selected_products))
                    with col3:
                        avg_per_product = total_reviews / len(selected_products) if selected_products else 0
                        st.metric("📈 Moyenne par produit", f"{avg_per_product:.0f} reviews")
                    
                    # Stocker pour l'interface d'export
                    st.session_state.estimated_volume = total_reviews
                else:
                    st.error("❌ Impossible d'obtenir les métriques")
            except Exception as e:
                st.error(f"❌ Erreur lors du calcul : {e}")


def display_export_interface():
    """Interface principale d'export"""
    if not st.session_state.get("selected_product_ids"):
        st.warning("⚠️ Aucun produit sélectionné. Chargez d'abord une configuration valide.")
        return
    
    st.markdown("---")
    st.header("🚀 Export des reviews")
    
    # Affichage des quotas
    with st.expander("📊 Quotas API actuels", expanded=False):
        display_quotas()
    
    # Options d'export
    st.markdown("### ⚙️ Options d'export")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### 📄 Paramètres de pagination")
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
        st.markdown("#### 🎯 Mode d'export")
        export_mode = st.radio(
            "Type d'export",
            ["🔍 Aperçu (50 reviews max)", "📦 Export complet"],
            help="L'aperçu permet de tester rapidement"
        )
        
        is_preview = export_mode.startswith("🔍")
        
        # Affichage de l'estimation
        estimated_volume = st.session_state.get("estimated_volume", "?")
        if is_preview:
            export_volume = min(50, estimated_volume) if isinstance(estimated_volume, int) else 50
            st.info(f"📊 Export prévu : {export_volume} reviews")
        else:
            st.info(f"📊 Export prévu : {estimated_volume} reviews")
    
    # Bouton de lancement
    st.markdown("---")
    if st.button("🚀 Lancer l'export", type="primary", key="launch_manual_export"):
        execute_manual_export(rows_per_page, use_random, random_seed, is_preview)


def execute_manual_export(rows_per_page, use_random, random_seed, is_preview):
    """Exécute l'export manuel"""
    
    # Vérification anti-double-export
    if st.session_state.get('export_in_progress', False):
        st.warning("⚠️ Un export est déjà en cours. Veuillez patienter.")
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
        
        # DIAGNOSTIC: Vérifier les métriques avant l'export
        st.markdown("### 🔍 Diagnostic des métriques")
        
        # Métriques sans limite de rows
        metrics_params = build_filter_params(filters, include_product_list=True)
        metrics = api_client.get_metrics(**metrics_params)
        total_available = metrics.get("nbDocs", 0) if metrics else 0
        
        st.write(f"**Métriques API :** {total_available} reviews attendues")
        st.write(f"**Paramètres métriques :** {metrics_params}")
        
        # Test avec rows=1 pour voir si la pagination fonctionne
        test_params = export_params.copy()
        test_params["rows"] = 1
        test_params["cursorMark"] = "*"
        
        st.write("**Test pagination avec rows=1 :**")
        test_result = api_client.get_reviews(**test_params)
        if test_result:
            st.write(f"- Docs reçus: {len(test_result.get('docs', []))}")
            st.write(f"- NextCursor: {test_result.get('nextCursorMark', 'None')}")
            st.write(f"- Cursor différent: {test_result.get('nextCursorMark') != '*'}")
        
        if total_available == 0:
            st.warning("❌ Aucune review disponible pour cette sélection")
            return
        
        # DIAGNOSTIC: Afficher tous les paramètres d'export
        st.write(f"**Paramètres d'export complets :** {export_params}")
        
        # Configuration selon le mode
        if is_preview:
            max_reviews = min(50, total_available)
            expected_pages = 1
            st.info(f"📊 Mode aperçu : Chargement de {max_reviews} reviews maximum")
        else:
            expected_pages = (total_available + rows_per_page - 1) // rows_per_page
            st.info(f"🔄 Export complet : {total_available:,} reviews...")
            
        # Interface de progression
        status_text = st.empty()
        progress_bar = None if is_preview else st.progress(0)
        
        # Variables de pagination
        cursor_mark = "*"
        page_count = 0
        all_docs = []
        max_iterations = 20 if not is_preview else 10  # Augmenter la limite pour diagnostic
        
        # Debug initial
        st.write(f"🔍 Debug: Démarrage avec cursorMark='*', rows={export_params['rows']}")
        
        # Boucle d'export
        while page_count < max_iterations:
            page_count += 1
            
            current_count = len(all_docs)
            status_text.text(f"📥 Page {page_count} | Récupéré: {current_count:,}/{total_available:,} reviews")
            
            # Paramètres avec cursor
            current_params = export_params.copy()
            current_params["cursorMark"] = cursor_mark
            
            # Debug des paramètres
            st.write(f"🔍 Page {page_count}: cursor='{cursor_mark}', rows={current_params['rows']}")
            st.write(f"🔍 Paramètres complets page {page_count}: {current_params}")
            
            # Appel API
            result = api_client.get_reviews(**current_params)
            
            if not result:
                st.error(f"❌ Pas de résultat API à la page {page_count}")
                break
                
            if not result.get("docs"):
                st.warning(f"⚠️ Pas de docs dans le résultat à la page {page_count}")
                st.write(f"🔍 Résultat complet: {result}")
                break
            
            docs = result.get("docs", [])
            
            # DIAGNOSTIC: Analyser les docs reçus
            st.write(f"🔍 Docs reçus page {page_count}:")
            if docs:
                # Afficher les IDs des premières reviews pour diagnostic
                sample_ids = [doc.get('id', 'NO_ID')[:10] for doc in docs[:3]]
                st.write(f"- Échantillon IDs: {sample_ids}")
                st.write(f"- Premier doc clés: {list(docs[0].keys())[:10]}")
            
            # Vérifier les doublons
            docs_before = len(all_docs)
            
            if all_docs and 'id' in docs[0]:
                existing_ids = {doc.get('id') for doc in all_docs if doc.get('id')}
                new_docs = [doc for doc in docs if doc.get('id') not in existing_ids]
                
                if len(new_docs) < len(docs):
                    duplicates_found = len(docs) - len(new_docs)
                    st.warning(f"⚠️ {duplicates_found} doublons détectés et ignorés à la page {page_count}")
                    
                    # DEBUG: Montrer quelques IDs dupliqués
                    duplicate_ids = [doc.get('id', 'NO_ID')[:10] for doc in docs if doc.get('id') in existing_ids][:3]
                    st.write(f"🔍 Exemples IDs dupliqués: {duplicate_ids}")
                
                all_docs.extend(new_docs)
            else:
                all_docs.extend(docs)
            
            docs_after = len(all_docs)
            st.write(f"📊 Page {page_count}: +{len(docs)} reçus, +{docs_after - docs_before} ajoutés (Total: {docs_after})")
            
            # Mise à jour progression
            if progress_bar is not None:
                progress_percent = min(len(all_docs) / total_available, 1.0)
                progress_bar.progress(progress_percent)
            
            # Gestion du cursor - DIAGNOSTIC APPROFONDI
            next_cursor = result.get("nextCursorMark")
            
            st.write(f"🔍 Cursor reçu: '{next_cursor}'")
            st.write(f"🔍 Cursor actuel: '{cursor_mark}'")
            st.write(f"🔍 Cursor identique: {next_cursor == cursor_mark}")
            st.write(f"🔍 Cursor vide: {not next_cursor}")
            
            # DIAGNOSTIC SUPPLÉMENTAIRE: Vérifier d'autres champs de réponse
            other_fields = {k: v for k, v in result.items() if k not in ['docs', 'nextCursorMark']}
            if other_fields:
                st.write(f"🔍 Autres champs réponse: {other_fields}")
            
            # CONDITIONS D'ARRÊT
            if not next_cursor:
                st.info(f"🏁 Fin: Pas de nextCursorMark")
                break
                
            if next_cursor == cursor_mark:
                st.info(f"🏁 Fin: Cursor identique ('{cursor_mark}')")
                # DIAGNOSTIC: Tenter une requête avec rows plus petit
                if page_count == 2 and export_params["rows"] > 10:
                    st.warning("🔧 Tentative avec rows=5 pour contourner le problème...")
                    current_params_small = current_params.copy()
                    current_params_small["rows"] = 5
                    test_result = api_client.get_reviews(**current_params_small)
                    if test_result:
                        st.write(f"🔍 Test rows=5: {len(test_result.get('docs', []))} docs, cursor: {test_result.get('nextCursorMark', 'None')}")
                break
            
            # MISE À JOUR DU CURSOR
            cursor_mark = next_cursor
            
            # Conditions d'arrêt supplémentaires
            if len(all_docs) >= total_available:
                st.info(f"🏁 Toutes les reviews récupérées ({len(all_docs)})")
                break
            
            # En mode aperçu, on s'arrête après avoir assez de reviews
            if is_preview and len(all_docs) >= 50:
                st.info("🔍 Limite aperçu atteinte")
                break
            
            # Pause entre requêtes
            if page_count % 3 == 0:
                time.sleep(0.2)
        
        # DIAGNOSTIC FINAL
        st.markdown("### 🔍 Diagnostic final")
        st.write(f"**Reviews récupérées :** {len(all_docs)}")
        st.write(f"**Reviews attendues :** {total_available}")
        st.write(f"**Pages parcourues :** {page_count}")
        st.write(f"**Dernier cursor :** {cursor_mark}")
        
        # Stocker les résultats
        st.session_state.all_docs = all_docs
        st.session_state.export_params = export_params
        st.session_state.is_preview_mode = is_preview
        
        # Messages finaux
        mode_text = "aperçu manuel" if is_preview else "export manuel complet"
        if all_docs:
            status_text.text(f"✅ {mode_text.capitalize()} terminé! {len(all_docs):,} reviews récupérées")
            
            # Log de l'activité
            if not is_preview:
                log_export_activity(export_params, len(all_docs), "MANUAL_SELECTION")
            
            st.balloons()
        else:
            status_text.text("⚠️ Aucune review récupérée")
    
    except Exception as e:
        st.error(f"❌ Erreur lors de l'export : {str(e)}")
        import traceback
        st.write(f"🔍 Stack trace: {traceback.format_exc()}")
    
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
    
    st.markdown("---")
    st.header("📋 Résultats de l'export")
    
    # Bandeau d'information
    if is_preview:
        st.info("ℹ️ Mode aperçu - Échantillon limité des données")
    else:
        st.success(f"✅ Export complet - {total_results:,} reviews récupérées")
    
    # Pagination pour l'affichage
    rows_per_page = 100
    total_pages = max(1, (total_results + rows_per_page - 1) // rows_per_page)
    
    # Contrôles de pagination
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col1:
        if st.button("⬅️ Page précédente", disabled=st.session_state.get("current_page", 1) <= 1):
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
        if st.button("➡️ Page suivante", disabled=st.session_state.get("current_page", 1) >= total_pages):
            st.session_state.current_page = min(total_pages, st.session_state.get("current_page", 1) + 1)
            st.rerun()
    
    # Affichage des données de la page courante
    start_idx = (current_page - 1) * rows_per_page
    end_idx = min(start_idx + rows_per_page, total_results)
    page_docs = docs[start_idx:end_idx]
    
    st.write(f"Affichage des reviews {start_idx + 1} à {end_idx} sur {total_results}")
    
    # Créer le DataFrame
    df_page = pd.json_normalize(page_docs)
    df_page = df_page.applymap(lambda x: str(x) if isinstance(x, (dict, list)) else x)
    
    # Afficher le tableau
    st.dataframe(df_page, use_container_width=True)
    
    # Boutons de téléchargement
    display_download_interface(docs, df_page, current_page)


def display_download_interface(all_docs, df_page, current_page):
    """Interface de téléchargement des résultats"""
    export_params = st.session_state.get("export_params", {})
    is_preview = st.session_state.get("is_preview_mode", False)
    
    st.markdown("### 💾 Téléchargements")
    
    # Avertissement Excel si nécessaire
    display_excel_warning()
    
    # Téléchargement de la page courante
    st.markdown("#### 📄 Page courante")
    
    page_filename_base = f"reviews_manuel_page{current_page}"
    display_download_buttons(df_page, page_filename_base, mode="page", page=current_page)
    
    # Téléchargement complet
    st.markdown("#### 📦 Export complet")
    
    # Préparer les données complètes
    df_full = pd.json_normalize(all_docs)
    df_full = df_full.applymap(lambda x: str(x) if isinstance(x, (dict, list)) else x)
    
    full_filename_base = f"reviews_manuel_{'apercu' if is_preview else 'complet'}"
    display_download_buttons(df_full, full_filename_base, mode="complet")


def display_current_configuration_export():
    """Affiche la configuration actuelle pour export"""
    if not st.session_state.get("filters"):
        return
    
    st.markdown("---")
    st.header("💾 Configuration actuelle")
    
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
            "💾 Télécharger config",
            config_json,
            file_name="config_export_manuel.json",
            mime="application/json"
        )


def main():
    """Interface principale du module export manuel"""
    initialize_session_state()
    
    st.title("🎯 Module 2 - Export Manuel")
    st.markdown("Exportez une sélection manuelle de produits avec précision")
    
    # Interface de configuration
    display_configuration_interface()
    
    # Si configuration chargée
    if st.session_state.get("apply_filters") and st.session_state.get("filters"):
        # Résumé de la configuration
        display_configuration_summary()
        
        # Interface d'export
        display_export_interface()
        
        # Affichage des résultats
        display_export_results()
        
        # Configuration pour réutilisation
        display_current_configuration_export()
    
    else:
        st.markdown("""
        ## 👋 Bienvenue dans l'Export Manuel
        
        Ce module vous permet d'exporter précisément une sélection de produits.
        
        ### 🎯 Fonctionnalités :
        - **Import de configuration** depuis le Module 1 - Explorateur
        - **Export ciblé** des reviews pour les produits sélectionnés
        - **Modes aperçu et complet** selon vos besoins
        - **Formats multiples** : CSV, Excel, Format plat
        - **Pagination** pour navigation facile des résultats
        
        ### 📋 Pour commencer :
        1. **Chargez une configuration** créée avec le Module 1
        2. **Vérifiez** les filtres et produits sélectionnés
        3. **Estimez le volume** total de reviews
        4. **Lancez l'export** en mode aperçu ou complet
        5. **Téléchargez** les résultats dans le format souhaité
        
        ### 💡 Conseils :
        - Testez d'abord avec l'aperçu (50 reviews max)
        - L'export complet peut prendre du temps selon le volume
        - Les configurations sont réutilisables entre sessions
        """)


if __name__ == "__main__":
    main()
