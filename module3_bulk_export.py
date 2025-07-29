"""
Module 3 - Export Bulk (Masse)
Permet d'exporter massivement par marque sans sélection individuelle
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
    """Interface de chargement de configuration pour export bulk"""
    st.header("📥 Configuration d'export bulk")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown("### 📎 Charger une configuration existante")
        json_input = st.text_area(
            "Collez votre configuration JSON ici",
            height=200,
            help="Configuration générée par le Module 1 - Explorateur ou Module 2"
        )
        
        if st.button("🔄 Charger la configuration", type="primary"):
            if load_configuration_from_json(json_input):
                st.success("Configuration chargée avec succès !")
                # En mode bulk, on ignore la sélection spécifique de produits
                st.info("ℹ️ Mode bulk : La sélection spécifique de produits sera ignorée")
                st.rerun()
    
    with col2:
        st.markdown("### 📋 Configuration actuelle")
        if st.session_state.get("filters"):
            filters = st.session_state.filters
            
            st.metric("Marques", len(filters.get("brand", [])))
            st.metric("Catégorie", filters.get("category", "ALL"))
            st.metric("Période", f"{filters.get('start_date')} → {filters.get('end_date')}")
            
            if st.button("🗑️ Effacer la configuration"):
                st.session_state.filters = {}
                st.session_state.selected_product_ids = []
                st.session_state.apply_filters = False
                st.rerun()
        else:
            st.info("Aucune configuration chargée")


def display_bulk_configuration_summary():
    """Affiche le résumé de la configuration pour export bulk"""
    if not st.session_state.get("filters"):
        return
    
    filters = st.session_state.filters
    
    st.markdown("---")
    st.header("📋 Configuration d'export bulk")
    
    # Résumé des filtres
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 🔍 Filtres appliqués")
        st.markdown(f"**📅 Période :** `{filters['start_date']}` → `{filters['end_date']}`")
        st.markdown(f"**🏷️ Catégorie :** `{filters.get('category', 'ALL')}`")
        st.markdown(f"**🏷️ Sous-catégorie :** `{filters.get('subcategory', 'ALL')}`")
        st.markdown(f"**🌍 Pays :** `{', '.join(filters.get('country', [])) if filters.get('country') and 'ALL' not in filters.get('country', []) else 'Tous'}`")
    
    with col2:
        st.markdown("### 🏢 Marques sélectionnées")
        brands = filters.get("brand", [])
        if brands:
            st.markdown(f"**📦 Nombre de marques :** `{len(brands)}`")
            
            # Afficher les marques
            brands_text = ", ".join(f"`{brand}`" for brand in brands[:5])
            if len(brands) > 5:
                brands_text += f" ... (+{len(brands) - 5} autres)"
            st.markdown(f"**Marques :** {brands_text}")
        else:
            st.warning("⚠️ Aucune marque sélectionnée")
    
    # Estimation du volume total
    if brands:
        display_bulk_volume_estimation()


def display_bulk_volume_estimation():
    """Estime le volume total pour l'export bulk"""
    filters = st.session_state.filters
    brands = filters.get("brand", [])
    
    if not brands:
        st.warning("⚠️ Aucune marque sélectionnée")
        return
    
    st.markdown("### 📊 Estimation du volume bulk")
    
    if st.button("📈 Calculer le volume total par marque", key="estimate_bulk_volume"):
        with st.spinner("Calcul du volume bulk..."):
            try:
                # Paramètres pour toutes les marques en une fois
                bulk_params = build_filter_params(filters)
                # En mode bulk, on prend toutes les marques ensemble
                
                # Appel API pour obtenir les métriques globales
                metrics = api_client.get_metrics(**bulk_params)
                if metrics:
                    total_reviews = metrics.get("nbDocs", 0)
                    
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("📊 Volume total estimé", f"{total_reviews:,} reviews")
                    with col2:
                        st.metric("🏢 Marques", len(brands))
                    with col3:
                        avg_per_brand = total_reviews / len(brands) if brands else 0
                        st.metric("📈 Moyenne par marque", f"{avg_per_brand:.0f} reviews")
                    
                    # Estimation détaillée par marque (optionnel)
                    if st.checkbox("📋 Voir le détail par marque", key="show_brand_details_bulk"):
                        with st.spinner("Détail par marque..."):
                            brand_details = []
                            
                            for brand in brands:
                                # Paramètres spécifiques à chaque marque
                                brand_params = build_filter_params(filters)
                                # Remplacer la liste de marques par une seule marque
                                brand_params["brand"] = brand
                                
                                try:
                                    brand_metrics = api_client.get_metrics(**brand_params)
                                    brand_count = brand_metrics.get("nbDocs", 0) if brand_metrics else 0
                                except Exception as e:
                                    st.warning(f"Erreur pour la marque {brand}: {e}")
                                    brand_count = 0
                                
                                brand_details.append({
                                    "Marque": brand,
                                    "Reviews": brand_count
                                })
                            
                            # Affichage du tableau détaillé
                            if brand_details:
                                df_details = pd.DataFrame(brand_details)
                                df_details = df_details.sort_values("Reviews", ascending=False)
                                st.dataframe(df_details, use_container_width=True)
                                
                                # Vérification de cohérence
                                sum_individual = df_details["Reviews"].sum()
                                if abs(sum_individual - total_reviews) > total_reviews * 0.1:  # 10% de différence
                                    st.warning(f"⚠️ Différence détectée : Total groupé ({total_reviews:,}) ≠ Somme individuelle ({sum_individual:,})")
                                    st.info("💡 Cela peut être normal si des reviews mentionnent plusieurs marques")
                                else:
                                    st.success("✅ Cohérence vérifiée entre le total groupé et la somme individuelle")
                    
                    # Stocker pour l'interface d'export
                    st.session_state.estimated_bulk_volume = total_reviews
                else:
                    st.error("❌ Impossible d'obtenir les métriques globales")
            except Exception as e:
                st.error(f"❌ Erreur lors du calcul : {e}")
                st.write(f"🔍 Debug: Filtres = {filters}")
                st.write(f"🔍 Debug: Paramètres = {build_filter_params(filters) if filters else 'Aucun'}")
            except Exception as e:
                st.error(f"❌ Erreur lors du calcul : {e}")


def display_bulk_export_interface():
    """Interface principale d'export bulk"""
    if not st.session_state.get("filters", {}).get("brand"):
        st.warning("⚠️ Aucune marque sélectionnée. Chargez d'abord une configuration valide.")
        return
    
    st.markdown("---")
    st.header("🚀 Export bulk par marque")
    
    # Affichage des quotas
    with st.expander("📊 Quotas API actuels", expanded=False):
        display_quotas()
    
    # Options d'export bulk
    st.markdown("### ⚙️ Options d'export bulk")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### 📄 Paramètres de pagination")
        bulk_rows_per_page = st.number_input(
            "Reviews par page (bulk)",
            min_value=10,
            max_value=1000,
            value=500,
            step=50,
            help="Plus élevé = moins d'appels API mais plus de mémoire. Recommandé: 500+"
        )
        
        bulk_use_random = st.checkbox("Randomiser les résultats (bulk)")
        if bulk_use_random:
            bulk_random_seed = st.number_input(
                "Seed aléatoire (bulk)",
                min_value=1,
                max_value=9999,
                value=42
            )
        else:
            bulk_random_seed = None
    
    with col2:
        st.markdown("#### 🎯 Mode d'export bulk")
        bulk_export_mode = st.radio(
            "Type d'export bulk",
            ["🔍 Aperçu bulk (100 reviews max)", "📦 Export bulk complet"],
            help="L'aperçu permet de tester rapidement l'export de toutes les marques"
        )
        
        is_bulk_preview = bulk_export_mode.startswith("🔍")
        
        # Affichage de l'estimation
        estimated_volume = st.session_state.get("estimated_bulk_volume", "?")
        if is_bulk_preview:
            export_volume = min(100, estimated_volume) if isinstance(estimated_volume, int) else 100
            st.info(f"📊 Export bulk prévu : {export_volume} reviews (échantillon)")
        else:
            st.info(f"📊 Export bulk prévu : {estimated_volume} reviews (toutes les marques)")
        
        # Avantages du mode bulk
        st.success("""
        **Avantages du mode bulk :**
        ✅ Pas de sélection produit par produit
        ✅ Export rapide de milliers de reviews
        ✅ Idéal pour des analyses globales
        ✅ Moins d'appels API individuels
        """)
    
    # Bouton de lancement
    st.markdown("---")
    if st.button("🚀 Lancer l'export bulk", type="primary", key="launch_bulk_export"):
        execute_bulk_export(bulk_rows_per_page, bulk_use_random, bulk_random_seed, is_bulk_preview)


def execute_bulk_export(rows_per_page, use_random, random_seed, is_preview):
    """Exécute l'export bulk"""
    
    # Vérification anti-double-export
    if st.session_state.get('export_in_progress', False):
        st.warning("⚠️ Un export est déjà en cours. Veuillez patienter.")
        return
    
    # Marquer l'export comme en cours
    st.session_state.export_in_progress = True
    
    try:
        filters = st.session_state.filters
        
        # Construction des paramètres bulk (toutes les marques ensemble)
        bulk_params = build_filter_params(filters)
        # Ne pas inclure de sélection spécifique de produits en mode bulk
        
        bulk_params["rows"] = min(rows_per_page, 100) if is_preview else rows_per_page
        
        if use_random and random_seed:
            bulk_params["random"] = str(random_seed)
        
        # Obtenir le volume total
        metrics = api_client.get_metrics(**build_filter_params(filters))
        total_available = metrics.get("nbDocs", 0) if metrics else 0
        
        if total_available == 0:
            st.warning("❌ Aucune review disponible pour cette combinaison de marques")
            return
        
        # Configuration selon le mode
        if is_preview:
            max_reviews = min(100, total_available)
            expected_pages = 1
            st.info(f"📊 Mode aperçu bulk : Chargement de {max_reviews} reviews maximum sur {total_available:,} disponibles")
        else:
            expected_pages = (total_available + rows_per_page - 1) // rows_per_page
            st.info(f"🔄 Export bulk complet : {total_available:,} reviews sur {expected_pages} pages estimées")
        
        # Interface de progression
        status_text = st.empty()
        progress_bar = None if is_preview else st.progress(0)
        
        # Variables de pagination
        cursor_mark = "*"
        page_count = 0
        all_docs = []
        max_iterations = 1000 if not is_preview else 1
        
        # Boucle d'export bulk
        while page_count < max_iterations:
            page_count += 1
            
            current_count = len(all_docs)
            status_text.text(f"📥 Page {page_count} | Récupéré: {current_count:,}/{total_available:,} reviews (bulk)")
            
            # Paramètres avec cursor
            current_params = bulk_params.copy()
            current_params["cursorMark"] = cursor_mark
            
            # Debug des premières pages
            if page_count <= 3:
                st.write(f"🔍 Debug bulk page {page_count}: cursor={cursor_mark[:20]}...")
            
            # Appel API
            result = api_client.get_reviews(**current_params)
            
            if not result:
                st.error(f"❌ Erreur API à la page {page_count}")
                break
            
            if not result.get("docs"):
                st.warning(f"⚠️ Pas de données à la page {page_count}")
                break
            
            docs = result.get("docs", [])
            all_docs.extend(docs)
            
            # Affichage du progrès détaillé
            st.write(f"📊 Page {page_count}: +{len(docs)} reviews (Total: {len(all_docs):,})")
            
            # Mise à jour progression
            if progress_bar is not None:
                progress_percent = min(len(all_docs) / total_available, 1.0)
                progress_bar.progress(progress_percent)
            
            # En mode aperçu, on s'arrête après la première page
            if is_preview:
                break
            
            # Gestion du cursor
            next_cursor = result.get("nextCursorMark")
            
            # Debug du cursor
            if page_count <= 3:
                st.write(f"🔍 Cursor actuel: {cursor_mark[:20]}...")
                st.write(f"🔍 Cursor suivant: {next_cursor[:20] if next_cursor else 'None'}...")
            
            # Conditions d'arrêt
            if not next_cursor:
                st.info(f"🏁 Fin de pagination bulk: pas de cursor suivant")
                break
            
            if next_cursor == cursor_mark:
                st.info(f"🏁 Fin de pagination bulk: cursor identique")
                break
            
            if len(all_docs) >= total_available:
                st.info(f"🏁 Toutes les reviews récupérées en bulk ({len(all_docs):,})")
                break
            
            cursor_mark = next_cursor
            
            # Limite aperçu
            if is_preview and len(all_docs) >= 100:
                break
            
            # Pause entre requêtes pour éviter les limites
            if page_count % 10 == 0:
                time.sleep(0.1)
        
        # Stocker les résultats
        st.session_state.all_docs = all_docs
        st.session_state.export_params = bulk_params
        st.session_state.is_preview_mode = is_preview
        
        # Messages finaux
        mode_text = "aperçu bulk" if is_preview else "export bulk complet"
        if all_docs:
            success_msg = f"✅ {mode_text.capitalize()} terminé! {len(all_docs):,} reviews récupérées sur {total_available:,} attendues"
            status_text.text(success_msg)
            
            # Avertissement si pas toutes les reviews en mode complet
            if len(all_docs) < total_available and not is_preview:
                st.warning(f"⚠️ Attention: {total_available - len(all_docs):,} reviews manquantes")
            
            st.balloons()  # Célébration pour les gros exports !
            
            # Log de l'activité
            if not is_preview:
                log_export_activity(bulk_params, len(all_docs), "BULK_BY_BRAND")
            
        else:
            status_text.text("⚠️ Aucune review récupérée en mode bulk")
    
    except Exception as e:
        st.error(f"❌ Erreur lors de l'export bulk : {str(e)}")
        st.write(f"🔍 Debug: Page {page_count}, Reviews récupérées: {len(all_docs) if 'all_docs' in locals() else 0}")
    
    finally:
        # Toujours libérer le verrou
        st.session_state.export_in_progress = False


def display_bulk_export_results():
    """Affiche les résultats de l'export bulk"""
    if not st.session_state.get("all_docs"):
        return
    
    docs = st.session_state.all_docs
    total_results = len(docs)
    is_preview = st.session_state.get("is_preview_mode", False)
    
    st.markdown("---")
    st.header("📋 Résultats de l'export bulk")
    
    # Bandeau d'information
    if is_preview:
        st.info("ℹ️ Mode aperçu bulk - Échantillon représentatif de toutes les marques")
    else:
        st.success(f"✅ Export bulk complet - {total_results:,} reviews de toutes les marques sélectionnées")
    
    # Statistiques rapides
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("📊 Total reviews", f"{total_results:,}")
    
    with col2:
        # Compter les marques uniques dans les résultats
        df_temp = pd.json_normalize(docs)
        unique_brands = df_temp.get('brand', pd.Series()).nunique() if 'brand' in df_temp.columns else "N/A"
        st.metric("🏢 Marques représentées", unique_brands)
    
    with col3:
        # Compter les produits uniques
        unique_products = df_temp.get('product', pd.Series()).nunique() if 'product' in df_temp.columns else "N/A"
        st.metric("📦 Produits uniques", unique_products)
    
    with col4:
        # Période couverte
        if 'date' in df_temp.columns:
            date_range = "Voir données"
        else:
            date_range = "N/A"
        st.metric("📅 Période", date_range)
    
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
            key="bulk_page_selector"
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
    
    st.write(f"Affichage des reviews {start_idx + 1} à {end_idx} sur {total_results:,} (Export bulk)")
    
    # Créer le DataFrame
    df_page = pd.json_normalize(page_docs)
    df_page = df_page.applymap(lambda x: str(x) if isinstance(x, (dict, list)) else x)
    
    # Afficher le tableau
    st.dataframe(df_page, use_container_width=True)
    
    # Boutons de téléchargement
    display_bulk_download_interface(docs, df_page, current_page)


def display_bulk_download_interface(all_docs, df_page, current_page):
    """Interface de téléchargement des résultats bulk"""
    is_preview = st.session_state.get("is_preview_mode", False)
    
    st.markdown("### 💾 Téléchargements bulk")
    
    # Avertissement Excel si nécessaire
    display_excel_warning()
    
    # Téléchargement de la page courante
    st.markdown("#### 📄 Page courante")
    
    page_filename_base = f"reviews_bulk_page{current_page}"
    display_download_buttons(df_page, page_filename_base, mode="page", page=current_page)
    
    # Téléchargement complet bulk
    st.markdown("#### 📦 Export bulk complet")
    
    # Préparer les données complètes
    df_full = pd.json_normalize(all_docs)
    df_full = df_full.applymap(lambda x: str(x) if isinstance(x, (dict, list)) else x)
    
    # Informations sur le dataset complet
    st.info(f"📊 Dataset complet : {len(all_docs):,} reviews, {df_full.shape[1]} colonnes")
    
    full_filename_base = f"reviews_bulk_{'apercu' if is_preview else 'complet'}"
    display_download_buttons(df_full, full_filename_base, mode="bulk_complet")


def display_bulk_analytics():
    """Affiche des analyses rapides des données bulk"""
    if not st.session_state.get("all_docs"):
        return
    
    st.markdown("---")
    st.header("📈 Analyses rapides (Bulk)")
    
    docs = st.session_state.all_docs
    df = pd.json_normalize(docs)
    
    if df.empty:
        st.warning("Aucune donnée à analyser")
        return
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 🏢 Répartition par marque")
        if 'brand' in df.columns:
            brand_counts = df['brand'].value_counts().head(10)
            st.bar_chart(brand_counts)
        else:
            st.info("Colonne 'brand' non disponible")
    
    with col2:
        st.markdown("### ⭐ Répartition des notes")
        if 'rating' in df.columns:
            rating_counts = df['rating'].value_counts().sort_index()
            st.bar_chart(rating_counts)
        elif 'note' in df.columns:
            rating_counts = df['note'].value_counts().sort_index()
            st.bar_chart(rating_counts)
        else:
            st.info("Colonne de notation non disponible")
    
    # Tableau récapitulatif
    st.markdown("### 📊 Résumé statistique")
    
    summary_data = []
    
    # Nombre total
    summary_data.append({"Métrique": "Total reviews", "Valeur": f"{len(df):,}"})
    
    # Marques uniques
    if 'brand' in df.columns:
        summary_data.append({"Métrique": "Marques uniques", "Valeur": df['brand'].nunique()})
    
    # Produits uniques
    if 'product' in df.columns:
        summary_data.append({"Métrique": "Produits uniques", "Valeur": df['product'].nunique()})
    
    # Pays uniques
    if 'country' in df.columns:
        summary_data.append({"Métrique": "Pays représentés", "Valeur": df['country'].nunique()})
    
    # Période
    if 'date' in df.columns:
        try:
            df['date_parsed'] = pd.to_datetime(df['date'], errors='coerce')
            min_date = df['date_parsed'].min()
            max_date = df['date_parsed'].max()
            if pd.notna(min_date) and pd.notna(max_date):
                summary_data.append({"Métrique": "Période couverte", "Valeur": f"{min_date.strftime('%Y-%m-%d')} → {max_date.strftime('%Y-%m-%d')}"})
        except:
            pass
    
    if summary_data:
        summary_df = pd.DataFrame(summary_data)
        st.dataframe(summary_df, use_container_width=True)


def display_current_bulk_configuration():
    """Affiche la configuration bulk actuelle pour export"""
    if not st.session_state.get("filters"):
        return
    
    st.markdown("---")
    st.header("💾 Configuration bulk actuelle")
    
    # Configuration sans sélection spécifique de produits (mode bulk)
    export_config = export_configuration_to_json(
        st.session_state.filters,
        selected_products=None  # Pas de sélection spécifique en mode bulk
    )
    
    # Ajouter une note sur le mode bulk
    export_config["export_mode"] = "BULK_BY_BRAND"
    export_config["note"] = "Configuration pour export bulk - tous les produits des marques sélectionnées"
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown("Configuration JSON pour export bulk :")
        st.code(json.dumps(export_config, indent=2), language="json")
    
    with col2:
        # Bouton de téléchargement
        config_json = json.dumps(export_config, indent=2)
        st.download_button(
            "💾 Télécharger config bulk",
            config_json,
            file_name="config_export_bulk.json",
            mime="application/json"
        )
        
        # Informations sur la config
        st.info("""
        **Cette configuration :**
        ✅ Inclut tous les filtres
        ✅ Mode bulk activé
        ✅ Pas de sélection produit
        ✅ Réutilisable dans ce module
        """)


def main():
    """Interface principale du module export bulk"""
    initialize_session_state()
    
    st.title("🚀 Module 3 - Export Bulk")
    st.markdown("Exportez massivement par marque sans sélection individuelle de produits")
    
    # Interface de configuration
    display_configuration_interface()
    
    # Si configuration chargée
    if st.session_state.get("apply_filters") and st.session_state.get("filters"):
        # Résumé de la configuration bulk
        display_bulk_configuration_summary()
        
        # Interface d'export bulk
        display_bulk_export_interface()
        
        # Affichage des résultats
        display_bulk_export_results()
        
        # Analyses rapides
        display_bulk_analytics()
        
        # Configuration pour réutilisation
        display_current_bulk_configuration()
    
    else:
        st.markdown("""
        ## 👋 Bienvenue dans l'Export Bulk
        
        Ce module vous permet d'exporter massivement toutes les reviews des marques sélectionnées.
        
        ### 🚀 Avantages du mode bulk :
        - **Export rapide en masse** : Toutes les reviews des marques en une fois
        - **Pas de sélection produit** : Automatiquement tous les produits
        - **Idéal pour l'analyse** : Datasets complets pour études approfondies
        - **Moins d'appels API** : Pagination optimisée pour gros volumes
        
        ### 📋 Pour commencer :
        1. **Chargez une configuration** (Module 1 ou 2)
        2. **Vérifiez** les marques sélectionnées
        3. **Estimez le volume** total toutes marques confondues
        4. **Lancez l'export bulk** en mode aperçu ou complet
        5. **Analysez** et téléchargez les résultats
        
        ### 💡 Cas d'usage parfaits :
        - Analyse concurrentielle multi-marques
        - Études de marché sectorielles  
        - Benchmarking produits à grande échelle
        - Constitution de datasets d'entraînement
        
        ### ⚠️ Recommandations :
        - Testez d'abord avec l'aperçu (100 reviews)
        - Les exports complets peuvent être très volumineux
        - Surveillez vos quotas API
        - Utilisez des filtres temporels pour limiter le volume
        """)


if __name__ == "__main__":
    main()
