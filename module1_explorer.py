"""
Module 1 - Explorateur de l'API Ratings & Reviews
Permet d'explorer le contenu de l'API pour préparer sa sélection
"""
import streamlit as st
import pandas as pd
import datetime
import json
from api_client import api_client
from utils import (
    initialize_session_state, 
    build_filter_params, 
    load_configuration_from_json, 
    export_configuration_to_json,
    format_nombre
)
from charte import encadre_cle, section

# Choix de la stratégie de traitement (libellés affichés ET valeurs comparées dans le code)
STRATEGIE_PRECISE = "Sélection précise de produits (recommandé pour analyses ciblées)"
STRATEGIE_MASSE = "Export en masse par marque (recommandé pour beaucoup de produits)"


def display_filter_interface():
    """Affiche l'interface de filtrage dans la sidebar"""
    with st.sidebar:
        st.header("Filtres d'exploration", anchor=False)
        
        # Section import de configuration
        st.markdown("### Charger une configuration")
        json_input = st.text_area(
            "Collez ici vos paramètres (JSON)", 
            height=150,
            help="Collez une configuration JSON précédemment exportée"
        )
        
        if st.button("Charger la configuration", icon=":material/upload_file:"):
            if load_configuration_from_json(json_input):
                st.rerun()
        
        st.markdown("---")
        
        # Filtres de base
        st.markdown("### Période")
        start_date = st.date_input("Date de début", value=datetime.date(2022, 1, 1))
        end_date = st.date_input("Date de fin", value=datetime.date.today())
        
        # Catégories
        st.markdown("### Catégories")
        categories_data = api_client.get_categories()
        all_categories = ["ALL"] + [c["category"] for c in categories_data.get("categories", [])]
        category = st.selectbox("Catégorie", all_categories)
        
        # Sous-catégories
        subcategory_options = ["ALL"]
        if category != "ALL":
            for cat in categories_data.get("categories", []):
                if cat["category"] == category:
                    subcategory_options += cat["subcategories"]
        subcategory = st.selectbox("Sous-catégorie", subcategory_options)
        
        # Marques
        st.markdown("### Marques")
        brands_data = api_client.get_brands(category, subcategory)
        brand = st.multiselect("Marques", brands_data.get("brands", []))
        
        # Géographie
        st.markdown("### Géographie")
        countries_data = api_client.get_countries()
        all_countries = ["ALL"] + countries_data.get("countries", [])
        country = st.multiselect("Pays", all_countries)
        
        # Sources
        source_params = country[0] if country and country[0] != "ALL" else None
        sources_data = api_client.get_sources(source_params)
        all_sources = ["ALL"] + sources_data.get("sources", [])
        source = st.multiselect("Sources", all_sources)
        
        # Markets
        markets_data = api_client.get_markets()
        all_markets = ["ALL"] + markets_data.get("markets", [])
        market = st.multiselect("Markets", all_markets)
        
        # Attributs
        st.markdown("### Attributs")
        attribute_data = api_client.get_attributes(category, subcategory, brand)
        attribute_options = attribute_data.get("attributes", [])
        attributes = st.multiselect("Attributs", attribute_options)
        attributes_positive = st.multiselect("Attributs positifs", attribute_options)
        attributes_negative = st.multiselect("Attributs négatifs", attribute_options)
        
        # Bouton d'application
        if st.button("Appliquer les filtres", type="primary", icon=":material/filter_alt:"):
            st.session_state.apply_filters = True
            st.session_state.filters = {
                "start_date": start_date,
                "end_date": end_date,
                "category": category,
                "subcategory": subcategory,
                "brand": brand,
                "country": country,
                "source": source,
                "market": market,
                "attributes": attributes,
                "attributes_positive": attributes_positive,
                "attributes_negative": attributes_negative
            }
            # Réinitialiser les données de produits
            st.session_state.product_data_cache = []
            st.session_state.product_list_loaded = False
            st.session_state.reviews_counts_loaded = False
            st.rerun()


def display_filter_summary():
    """Affiche le résumé des filtres appliqués"""
    filters = st.session_state.filters
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown(f"**Période :** `{filters['start_date']}` → `{filters['end_date']}`")
        st.markdown(f"**Catégorie :** `{filters['category']}`")
        st.markdown(f"**Sous-catégorie :** `{filters['subcategory']}`")
        st.markdown(f"**Marques :** `{', '.join(filters['brand']) if filters['brand'] else 'Toutes'}`")
    
    with col2:
        st.markdown(f"**Pays :** `{', '.join(filters['country']) if filters['country'] and 'ALL' not in filters['country'] else 'Tous'}`")
        st.markdown(f"**Sources :** `{', '.join(filters['source']) if filters['source'] and 'ALL' not in filters['source'] else 'Toutes'}`")
        st.markdown(f"**Markets :** `{', '.join(filters['market']) if filters['market'] and 'ALL' not in filters['market'] else 'Tous'}`")
        st.markdown(f"**Attributs :** `{', '.join(filters['attributes']) if filters['attributes'] else 'Aucun'}`")


def load_products_data():
    """Charge la liste des produits selon les filtres"""
    filters = st.session_state.filters
    
    if not filters.get("brand"):
        st.error("Aucune marque sélectionnée : choisissez au moins une marque dans les filtres, puis appliquez-les.", icon=":material/error:")
        return
    
    with st.spinner("Chargement des produits…"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        product_data = []
        
        for i, brand in enumerate(filters["brand"]):
            progress = (i + 1) / len(filters["brand"])
            progress_bar.progress(progress)
            status_text.text(f"Chargement marque {i+1}/{len(filters['brand'])}: {brand}")
            
            try:
                products_data = api_client.get_products(
                    brand=brand,
                    category=filters["category"],
                    subcategory=filters["subcategory"],
                    start_date=filters["start_date"],
                    end_date=filters["end_date"],
                    country=filters.get("country"),
                    source=filters.get("source"),
                    market=filters.get("market")
                )
                
                if products_data and products_data.get("products"):
                    for product in products_data["products"]:
                        product_data.append({
                            "Marque": brand,
                            "Produit": product,
                            "Nombre d'avis": "Non chargé"
                        })
            except Exception as e:
                st.warning(f"Erreur pour la marque {brand}: {str(e)}")
        
        progress_bar.empty()
        status_text.empty()
    
    if product_data:
        st.session_state.product_data_cache = product_data
        st.session_state.product_list_loaded = True
        st.session_state.reviews_counts_loaded = False
        st.success(f"{format_nombre(len(product_data))} produits chargés.", icon=":material/check_circle:")
    else:
        st.error("Aucun produit trouvé pour ces filtres : élargissez la période ou les marques.", icon=":material/error:")


def load_reviews_counts():
    """Charge les compteurs d'avis pour les produits"""
    if not st.session_state.product_data_cache:
        st.error("Liste des produits non chargée : chargez-la d'abord (étape 1).", icon=":material/error:")
        return
    
    filters = st.session_state.filters
    filter_params = build_filter_params(filters)
    
    with st.spinner("Chargement des compteurs d'avis…"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        errors_count = 0
        
        for i, row in enumerate(st.session_state.product_data_cache):
            progress = (i + 1) / len(st.session_state.product_data_cache)
            progress_bar.progress(progress)
            
            product_name = row["Produit"]
            brand_name = row["Marque"]
            status_text.text(f"Chargement {i+1}/{len(st.session_state.product_data_cache)}: {brand_name} - {product_name[:30]}...")
            
            try:
                # Paramètres spécifiques au produit
                product_params = filter_params.copy()
                product_params["product"] = product_name
                product_params["brand"] = brand_name
                
                # Appel API pour les métriques
                metrics = api_client.get_metrics(**product_params)
                
                if metrics and isinstance(metrics, dict):
                    nb_reviews = metrics.get("nbDocs", 0)
                    st.session_state.product_data_cache[i]["Nombre d'avis"] = nb_reviews
                else:
                    st.session_state.product_data_cache[i]["Nombre d'avis"] = "Erreur API"
                    errors_count += 1
                    
            except Exception as e:
                st.session_state.product_data_cache[i]["Nombre d'avis"] = "Erreur"
                errors_count += 1
        
        progress_bar.empty()
        status_text.empty()
        
        if errors_count > 0:
            st.warning(f"{errors_count} erreurs lors du chargement des compteurs : certains produits n'ont pas de nombre d'avis.", icon=":material/warning:")
        else:
            st.success(f"Compteurs chargés pour {format_nombre(len(st.session_state.product_data_cache))} produits.", icon=":material/check_circle:")
        
        st.session_state.reviews_counts_loaded = True


def display_products_interface():
    """Affiche l'interface de gestion des produits"""
    # Affichage de l'estimation des volumes avant de choisir la stratégie
    display_volume_strategy_selector()
    
    # Étapes de chargement
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### Étape 1 : liste des produits")
        if not st.session_state.product_list_loaded:
            if st.button("Charger la liste des produits", key="load_products", type="primary", icon=":material/inventory_2:"):
                load_products_data()
        else:
            st.success(f"{format_nombre(len(st.session_state.product_data_cache))} produits chargés.", icon=":material/check_circle:")
            if st.button("Recharger la liste", key="reload_products", icon=":material/refresh:"):
                st.session_state.product_list_loaded = False
                st.session_state.reviews_counts_loaded = False
                st.session_state.product_data_cache = []
                st.rerun()
    
    with col2:
        st.markdown("#### Étape 2 : compteurs d'avis (facultatif)")
        if st.session_state.product_list_loaded:
            if not st.session_state.reviews_counts_loaded:
                if st.button("Charger les compteurs", key="load_counts", icon=":material/tag:"):
                    load_reviews_counts()
            else:
                st.success("Compteurs chargés.", icon=":material/check_circle:")
                if st.button("Recharger les compteurs", key="reload_counts", icon=":material/refresh:"):
                    load_reviews_counts()
        else:
            st.info("Chargez d'abord la liste des produits.", icon=":material/info:")
    
    # Affichage et sélection des produits
    if st.session_state.product_list_loaded and st.session_state.product_data_cache:
        st.markdown("#### Étape 3 : sélection des produits")
        display_product_selection()


def display_volume_strategy_selector():
    """Affiche l'estimation des volumes et le sélecteur de stratégie"""
    filters = st.session_state.filters
    
    if not filters.get("brand"):
        st.warning("Aucune marque sélectionnée : choisissez au moins une marque dans les filtres.", icon=":material/warning:")
        return
    
    st.markdown("#### Stratégie de traitement")
    
    # Sélecteur de stratégie
    export_strategy = st.radio(
        "Choisissez votre approche",
        [STRATEGIE_PRECISE, STRATEGIE_MASSE],
        key="export_strategy_choice",
        help="Choisissez dès maintenant pour optimiser le chargement des données"
    )
    
    st.session_state.export_strategy = export_strategy
    
    # Affichage d'informations selon la stratégie
    if export_strategy == STRATEGIE_MASSE:
        st.success("Mode rapide : pas de chargement de la liste des produits.", icon=":material/bolt:")
        st.info(f"Tous les avis seront exportés pour : {', '.join(filters['brand'])}", icon=":material/info:")
        
        # Estimation du volume total en mode bulk
        display_bulk_volume_preview()
        
    else:
        st.info("Mode précis : la liste des produits va être chargée.", icon=":material/info:")
        
        # Estimation du nombre de produits à charger
        display_products_estimation()


def display_bulk_volume_preview():
    """Affiche un aperçu du volume en mode bulk"""
    filters = st.session_state.filters
    
    if st.button("Estimer le volume total", key="estimate_bulk_preview", type="primary", icon=":material/calculate:"):
        with st.spinner("Estimation du volume bulk..."):
            try:
                # Paramètres pour toutes les marques en une fois
                bulk_params = build_filter_params(filters)
                
                # Appel API pour obtenir les métriques globales
                metrics = api_client.get_metrics(**bulk_params)
                if metrics:
                    total_reviews = metrics.get("nbDocs", 0)
                    
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Volume total estimé", f"{format_nombre(total_reviews)} avis", border=True)
                    with col2:
                        st.metric("Marques", len(filters["brand"]), border=True)
                    with col3:
                        avg_per_brand = total_reviews / len(filters["brand"]) if filters["brand"] else 0
                        st.metric("Moyenne par marque", f"{format_nombre(round(avg_per_brand))} avis", border=True)
                    
                    if total_reviews > 10000:
                        st.success("Volume important : l'export en masse est le plus adapté.", icon=":material/check_circle:")
                    else:
                        st.info("Volume modéré : les deux modes conviennent.", icon=":material/info:")
                        
                else:
                    st.error("Volume indisponible : l'API n'a pas renvoyé de métriques. Réessayez dans un instant.", icon=":material/error:")
            except Exception as e:
                st.error(f"Calcul impossible : {e}. Réessayez dans un instant.", icon=":material/error:")


def display_products_estimation():
    """Affiche l'estimation du nombre de produits à charger"""
    filters = st.session_state.filters
    
    total_products_estimate = 0
    with st.spinner("Estimation du nombre de produits..."):
        # Faire une estimation groupée pour éviter trop d'appels API
        sample_brands = filters["brand"][:3]  # Échantillon de 3 marques max
        
        for brand in sample_brands:
            try:
                products = api_client.get_products(
                    brand=brand,
                    category=filters["category"],
                    subcategory=filters["subcategory"],
                    start_date=filters["start_date"],
                    end_date=filters["end_date"],
                    country=filters.get("country"),
                    source=filters.get("source"),
                    market=filters.get("market")
                )
                if products and products.get("products"):
                    total_products_estimate += len(products["products"])
            except Exception as e:
                st.warning(f"Erreur estimation pour {brand}: {e}")
    
    # Extrapoler pour toutes les marques
    if len(filters["brand"]) > len(sample_brands):
        avg_products_per_brand = total_products_estimate / len(sample_brands) if sample_brands else 0
        total_products_estimate = int(avg_products_per_brand * len(filters["brand"]))
    
    if total_products_estimate > 500:
        st.warning(f"Estimation : environ {format_nombre(total_products_estimate)} produits à charger. Cela peut prendre du temps et consommer du quota API.", icon=":material/warning:")
        
        # Estimation du nombre de reviews pour comparaison
        display_reviews_comparison()
        
        if st.button("Passer à l'export en masse", key="switch_to_bulk", icon=":material/swap_horiz:"):
            st.session_state.export_strategy = STRATEGIE_MASSE
            st.rerun()
    else:
        st.success(f"Estimation : environ {format_nombre(total_products_estimate)} produits à charger.", icon=":material/check_circle:")


def display_reviews_comparison():
    """Affiche une comparaison du volume de reviews pour aider à la décision"""
    filters = st.session_state.filters
    
    with st.spinner("Estimation du volume de reviews..."):
        try:
            estimation_params = build_filter_params(filters)
            
            total_reviews_metrics = api_client.get_metrics(**estimation_params)
            total_reviews = total_reviews_metrics.get("nbDocs", 0) if total_reviews_metrics else 0
            
            if total_reviews > 0:
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("Volume total d'avis", format_nombre(total_reviews), border=True)
                with col2:
                    st.metric("Produits estimés", f"~{st.session_state.get('products_estimate', '?')}", border=True)
                
                if total_reviews > 5000:
                    st.info("Avec ce volume, l'export en masse pourrait être plus efficace.", icon=":material/info:")
            
        except Exception as e:
            st.warning(f"Erreur estimation reviews: {e}")


def display_product_selection():
    """Affiche le tableau de sélection des produits"""
    product_data = st.session_state.product_data_cache
    
    if not product_data:
        st.warning("Aucun produit trouvé avec ces filtres.")
        return
    
    # Créer un DataFrame
    df_products = pd.DataFrame(product_data)
    
    # Interface de recherche
    search_text = st.text_input("Filtrer les produits", key="product_search", placeholder="Nom du produit ou de la marque")
    
    # Filtrer selon la recherche
    if search_text:
        mask = (df_products["Produit"].str.contains(search_text, case=False, na=False) | 
                df_products["Marque"].str.contains(search_text, case=False, na=False))
        filtered_df = df_products[mask]
    else:
        filtered_df = df_products
    
    # Boutons de tri
    col1, col2, col3 = st.columns([2, 2, 2])
    with col1:
        if st.button("Trier par marque", key="sort_brand"):
            st.session_state.sort_column = "Marque"
            st.session_state.sort_ascending = not st.session_state.get("sort_ascending", True)
    with col2:
        if st.button("Trier par produit", key="sort_product"):
            st.session_state.sort_column = "Produit"
            st.session_state.sort_ascending = not st.session_state.get("sort_ascending", True)
    with col3:
        if st.button("Trier par nb d'avis", key="sort_reviews"):
            st.session_state.sort_column = "Nombre d'avis"
            st.session_state.sort_ascending = not st.session_state.get("sort_ascending", False)
    
    # Appliquer le tri
    sort_column = st.session_state.get("sort_column", "Marque")
    sort_ascending = st.session_state.get("sort_ascending", True)
    
    if sort_column in filtered_df.columns:
        if sort_column == "Nombre d'avis":
            # Tri numérique pour les avis
            def sort_reviews(x):
                if isinstance(x, (int, float)):
                    return x
                elif str(x).isdigit():
                    return int(x)
                else:
                    return -1
            
            filtered_df = filtered_df.iloc[filtered_df["Nombre d'avis"].map(sort_reviews).argsort()]
            if not sort_ascending:
                filtered_df = filtered_df.iloc[::-1]
        else:
            filtered_df = filtered_df.sort_values(by=sort_column, ascending=sort_ascending)
    
    # Interface de sélection
    st.write(f"**{len(filtered_df)} produits** | Tri: {sort_column} ({'croissant' if sort_ascending else 'décroissant'})")
    
    # Sélection groupée
    col_sel_all, col_deselect_all, col_stats = st.columns([2, 2, 3])
    
    with col_sel_all:
        if st.button("Tout sélectionner (page)", key="select_all_visible", icon=":material/select_all:"):
            visible_products = list(filtered_df["Produit"].values)
            for pid in visible_products:
                if pid not in st.session_state.selected_product_ids:
                    st.session_state.selected_product_ids.append(pid)
            st.rerun()
    
    with col_deselect_all:
        if st.button("Tout désélectionner", key="deselect_all", icon=":material/deselect:"):
            st.session_state.selected_product_ids = []
            st.rerun()
    
    with col_stats:
        selected_count = len(st.session_state.selected_product_ids)
        st.metric("Produits sélectionnés", selected_count)
    
    # Tableau de sélection
    st.markdown("---")
    
    # En-têtes
    header_col1, header_col2, header_col3, header_col4 = st.columns([0.5, 2, 3, 1])
    with header_col1:
        st.write("**Choix**")
    with header_col2:
        st.write("**Marque**")
    with header_col3:
        st.write("**Produit**")
    with header_col4:
        st.write("**Nb avis**")
    
    # Lignes de données
    for index, row in filtered_df.iterrows():
        product_id = row["Produit"]
        
        col1, col2, col3, col4 = st.columns([0.5, 2, 3, 1])
        
        with col1:
            is_selected = st.checkbox(
                "",
                value=product_id in st.session_state.selected_product_ids,
                key=f"product_check_{index}_{hash(product_id)}"
            )
            
            # Mise à jour de la sélection
            if is_selected and product_id not in st.session_state.selected_product_ids:
                st.session_state.selected_product_ids.append(product_id)
            elif not is_selected and product_id in st.session_state.selected_product_ids:
                st.session_state.selected_product_ids.remove(product_id)
        
        with col2:
            st.write(row["Marque"])
        with col3:
            st.write(row["Produit"])
        with col4:
            reviews_count = row["Nombre d'avis"]
            if isinstance(reviews_count, (int, float)) and reviews_count >= 0:
                st.write(f"**{reviews_count:,}**")
            else:
                st.write(f"{reviews_count}")


def display_volume_estimation():
    """Affiche l'estimation du volume total"""
    if not st.session_state.selected_product_ids:
        return
    
    filters = st.session_state.filters
    
    # Estimation par produits sélectionnés
    if st.button("Calculer le volume total", key="calculate_volume", type="primary", icon=":material/calculate:"):
        with st.spinner("Calcul du volume total..."):
            total_reviews = 0
            details = []
            
            for product_id in st.session_state.selected_product_ids:
                # Trouver la marque correspondante
                brand = None
                for row in st.session_state.product_data_cache:
                    if row["Produit"] == product_id:
                        brand = row["Marque"]
                        break
                
                if brand:
                    # Paramètres pour ce produit
                    params = build_filter_params(filters)
                    params.update({
                        "product": product_id,
                        "brand": brand
                    })
                    
                    try:
                        metrics = api_client.get_metrics(**params)
                        if metrics:
                            nb_reviews = metrics.get("nbDocs", 0)
                            total_reviews += nb_reviews
                            details.append({
                                "Produit": product_id,
                                "Marque": brand,
                                "Reviews": nb_reviews
                            })
                    except Exception as e:
                        st.warning(f"Erreur pour {product_id}: {e}")
            
            # Affichage des résultats
            if details:
                col1, col2 = st.columns([1, 2])
                
                with col1:
                    st.metric("Volume total", f"{format_nombre(total_reviews)} avis", border=True)
                    st.metric("Produits sélectionnés", len(details), border=True)
                
                with col2:
                    # Tableau détaillé
                    df_details = pd.DataFrame(details)
                    df_details = df_details.sort_values("Reviews", ascending=False)
                    st.dataframe(df_details, use_container_width=True)


def display_export_configuration():
    """Affiche la configuration d'export réutilisable"""
    if not st.session_state.get("filters"):
        return
    
    # Inclure la stratégie choisie dans la configuration
    export_config = export_configuration_to_json(
        st.session_state.filters,
        st.session_state.selected_product_ids
    )
    
    # Ajouter des métadonnées sur la stratégie
    strategy = st.session_state.get("export_strategy", "")
    if strategy == STRATEGIE_MASSE:
        export_config["export_mode"] = "BULK_BY_BRAND"
        export_config["note"] = "Configuration optimisée pour export en masse"
    else:
        export_config["export_mode"] = "MANUAL_SELECTION"
        export_config["note"] = "Configuration avec sélection précise de produits"
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown("Copiez cette configuration pour la réutiliser dans les modules d'export :")
        st.code(json.dumps(export_config, indent=2), language="json")
    
    with col2:
        # Bouton de téléchargement
        config_json = json.dumps(export_config, indent=2)
        st.download_button(
            "Télécharger la configuration",
            config_json,
            file_name="configuration_export.json",
            mime="application/json",
            icon=":material/download:"
        )
        
        # Recommandation de module
        strategy = st.session_state.get("export_strategy", "")
        if strategy == STRATEGIE_MASSE:
            encadre_cle("Utilisez l'Export par segment pour cette configuration.", titre="Recommandation")
        else:
            encadre_cle("Utilisez l'Export manuel pour cette configuration.", titre="Recommandation")


def main():
    """Interface principale du module explorateur"""
    initialize_session_state()

    # Interface de filtrage
    display_filter_interface()

    # Interface principale
    if st.session_state.get("apply_filters") and st.session_state.get("filters"):
        with section("Filtres appliqués"):
            display_filter_summary()

        with section("Produits", "Choisissez la stratégie, puis chargez et sélectionnez les produits."):
            display_products_interface()

        # Estimation du volume
        if st.session_state.selected_product_ids and st.session_state.get("export_strategy") == STRATEGIE_PRECISE:
            with section("Volume total de la sélection"):
                display_volume_estimation()

        with section("Configuration réutilisable",
                     "À copier ou télécharger, puis à importer dans un module d'export."):
            display_export_configuration()

    else:
        with section("Comment utiliser l'Explorateur API",
                     "Configurez vos filtres dans la barre latérale, puis cliquez sur « Appliquer les filtres »."):
            st.markdown("""
            1. **Configurez vos filtres** dans la barre latérale
            2. **Appliquez les filtres** pour voir les options disponibles
            3. **Chargez la liste des produits** correspondant à vos critères
            4. **Facultatif :** chargez les compteurs d'avis pour chaque produit
            5. **Sélectionnez les produits** qui vous intéressent un par un
            6. **Estimez le volume total** de votre sélection
            7. **Exportez la configuration** pour l'utiliser dans les modules d'export

            Conseils : commencez par des filtres larges puis affinez ; le chargement des compteurs peut prendre
            du temps pour beaucoup de produits ; sauvegardez votre configuration pour la réutiliser.
            """)


if __name__ == "__main__":
    main()
