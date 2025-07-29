"""
Utilitaires partagés pour l'explorateur Ratings & Reviews
"""
import streamlit as st
import pandas as pd
import datetime
import json
import ast
from pathlib import Path
import io

# Vérification des dépendances optionnelles
try:
    import openpyxl
    EXCEL_AVAILABLE = True
except ImportError:
    EXCEL_AVAILABLE = False


def initialize_session_state():
    """Initialise les variables de session par défaut"""
    session_defaults = {
        "apply_filters": False,
        "cursor_mark": "*",
        "current_page": 1,
        "all_docs": [],
        "next_cursor": None,
        "selected_product_ids": [],
        "is_preview_mode": True,
        "export_params": {},
        "switch_to_full_export": False,
        "sort_column": "Nombre d'avis",
        "sort_ascending": False,
        "filters": {},
        "export_strategy": None,
        "product_data_cache": [],
        "product_list_loaded": False,
        "reviews_counts_loaded": False,
        "export_in_progress": False
    }
    
    for key, default_value in session_defaults.items():
        st.session_state.setdefault(key, default_value)


def build_filter_params(filters, include_product_list=False):
    """Construit les paramètres d'API à partir des filtres"""
    params = {}
    
    # Dates
    if filters.get("start_date"):
        params["start-date"] = filters["start_date"]
    if filters.get("end_date"):
        params["end-date"] = filters["end_date"]
    
    # Catégories
    if filters.get("category") and filters["category"] != "ALL":
        params["category"] = filters["category"]
    if filters.get("subcategory") and filters["subcategory"] != "ALL":
        params["subcategory"] = filters["subcategory"]
    
    # Marques
    if filters.get("brand"):
        params["brand"] = ",".join(filters["brand"])
    
    # Géographie
    if filters.get("country") and "ALL" not in filters.get("country", []):
        params["country"] = ",".join(filters["country"])
    if filters.get("source") and "ALL" not in filters.get("source", []):
        params["source"] = ",".join(filters["source"])
    if filters.get("market") and "ALL" not in filters.get("market", []):
        params["market"] = ",".join(filters["market"])
    
    # Attributs
    if filters.get("attributes"):
        params["attribute"] = ",".join(filters["attributes"])
    if filters.get("attributes_positive"):
        params["attribute-positive"] = ",".join(filters["attributes_positive"])
    if filters.get("attributes_negative"):
        params["attribute-negative"] = ",".join(filters["attributes_negative"])
    
    # Produits sélectionnés (pour export manuel)
    if include_product_list and st.session_state.get("selected_product_ids"):
        params["product"] = ",".join(st.session_state.selected_product_ids)
    
    return params


def generate_export_filename(params, mode="complete", page=None, extension="csv"):
    """Génère un nom de fichier basé sur les paramètres d'export"""
    filename_parts = ["reviews"]
    
    # Pays
    country = params.get("country", "").strip() if isinstance(params.get("country"), str) else ""
    if country:
        filename_parts.append(country.lower())
    
    # Produits (limiter à 2 pour éviter des noms trop longs)
    products = params.get("product", "").split(",") if isinstance(params.get("product"), str) else []
    if products and products[0]:
        clean_products = []
        for p in products[:2]:
            clean_p = p.strip().lower().replace(" ", "_").replace("/", "-")
            if len(clean_p) > 15:
                clean_p = clean_p[:15]
            clean_products.append(clean_p)
        if clean_products:
            filename_parts.append("-".join(clean_products))
            if len(products) > 2:
                filename_parts[-1] += "-plus"
    
    # Dates
    start_date = params.get("start-date")
    end_date = params.get("end-date")
    
    if start_date is not None and end_date is not None:
        start_date_str = str(start_date).replace("-", "")
        end_date_str = str(end_date).replace("-", "")
        
        if len(start_date_str) >= 8 and len(end_date_str) >= 8:
            if start_date_str[:4] == end_date_str[:4]:
                date_str = f"{start_date_str[:4]}_{start_date_str[4:8]}-{end_date_str[4:8]}"
            else:
                date_str = f"{start_date_str}-{end_date_str}"
            filename_parts.append(date_str)
    
    # Mode
    if mode == "preview":
        filename_parts.append("apercu")
    elif mode == "page":
        filename_parts.append(f"page{page}")
    
    # Assembler le nom
    filename = "_".join(filename_parts) + f".{extension}"
    
    # Limiter la longueur
    if len(filename) > 100:
        base, ext = filename.rsplit(".", 1)
        filename = base[:96] + "..." + "." + ext
    
    return filename


def load_configuration_from_json(json_input):
    """Charge les filtres depuis un JSON"""
    try:
        # Nettoyer l'input
        cleaned_input = json_input.strip()
        
        if not cleaned_input.startswith('{'):
            st.error("❌ Le JSON doit commencer par '{'")
            return False
        
        # Parser le JSON
        try:
            parsed = json.loads(cleaned_input)
        except json.JSONDecodeError as e:
            st.error(f"❌ Erreur JSON à la ligne {e.lineno}, position {e.colno}: {e.msg}")
            st.error("Vérifiez que :")
            st.error("- Toutes les clés et valeurs sont entre guillemets")
            st.error("- Il y a des virgules entre chaque paire clé-valeur")
            st.error("- Les dates sont au format 'YYYY-MM-DD' entre guillemets")
            st.error("- Pas de virgule après le dernier élément")
            
            # Exemple de JSON valide
            example_json = {
                "start-date": "2025-01-01",
                "end-date": "2025-04-30",
                "brand": "AVÈNE,aderma,arthrodont,BIODERMA",
                "category": "bodycare",
                "subcategory": "body creams & milks",
                "country": "France",
                "selected_products": ["Product1", "Product2"]
            }
            st.info("📝 Exemple de JSON valide :")
            st.code(json.dumps(example_json, indent=2), language="json")
            return False
        
        # Convertir les dates
        for key in ["start-date", "end-date"]:
            if isinstance(parsed.get(key), str):
                date_str = parsed[key]
                try:
                    parsed[key] = pd.to_datetime(date_str).date()
                except:
                    st.warning(f"Impossible de parser la date {key}: {date_str}")
                    parsed[key] = datetime.date.today()
        
        # Traiter les listes
        def process_list_field(field_name):
            if parsed.get(field_name):
                if isinstance(parsed[field_name], str):
                    return [item.strip() for item in parsed[field_name].split(",") if item.strip()]
                elif isinstance(parsed[field_name], list):
                    return parsed[field_name]
            return []
        
        # Injecter dans les filtres
        st.session_state.apply_filters = True
        st.session_state.filters = {
            "start_date": parsed.get("start-date", datetime.date(2022, 1, 1)),
            "end_date": parsed.get("end-date", datetime.date.today()),
            "category": parsed.get("category", "ALL"),
            "subcategory": parsed.get("subcategory", "ALL"),
            "brand": process_list_field("brand"),
            "country": process_list_field("country"),
            "source": process_list_field("source"),
            "market": process_list_field("market"),
            "attributes": process_list_field("attributes"),
            "attributes_positive": process_list_field("attributes_positive"),
            "attributes_negative": process_list_field("attributes_negative")
        }
        
        # Charger la sélection de produits si disponible
        selected_products = process_list_field("selected_products")
        if selected_products:
            st.session_state.selected_product_ids = selected_products
        
        st.success("✅ Configuration chargée avec succès.")
        st.info(f"📊 Résumé : {len(st.session_state.filters['brand'])} marque(s), du {parsed.get('start-date')} au {parsed.get('end-date')}")
        
        return True
        
    except Exception as e:
        st.error(f"❌ Erreur lors du parsing : {e}")
        st.error("💡 Astuce : Vérifiez que votre JSON est valide sur jsonlint.com")
        return False


def export_configuration_to_json(filters, selected_products=None):
    """Exporte la configuration actuelle en JSON"""
    export_config = {
        "start-date": str(filters["start_date"]),
        "end-date": str(filters["end_date"]),
        "category": filters.get("category", "ALL"),
        "subcategory": filters.get("subcategory", "ALL")
    }
    
    # Ajouter les listes non vides
    if filters.get("brand"):
        export_config["brand"] = ",".join(filters["brand"])
    if filters.get("country") and "ALL" not in filters["country"]:
        export_config["country"] = ",".join(filters["country"])
    if filters.get("source") and "ALL" not in filters["source"]:
        export_config["source"] = ",".join(filters["source"])
    if filters.get("market") and "ALL" not in filters["market"]:
        export_config["market"] = ",".join(filters["market"])
    if filters.get("attributes"):
        export_config["attributes"] = filters["attributes"]
    if filters.get("attributes_positive"):
        export_config["attributes_positive"] = filters["attributes_positive"]
    if filters.get("attributes_negative"):
        export_config["attributes_negative"] = filters["attributes_negative"]
    
    # Ajouter les produits sélectionnés
    if selected_products:
        export_config["selected_products"] = selected_products
    
    return export_config


def postprocess_reviews(df):
    """Fonction de postprocessing des reviews"""
    if df.empty:
        return df
    
    # Renommage des colonnes
    df.rename(columns={
        'id': 'guid',
        'category': 'categories',
        'content trad': 'verbatim_content',
        'product': 'product_name_SEMANTIWEB'
    }, inplace=True)
    
    # Traitement des dates
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'], errors='coerce')
        df['date'] = df['date'].dt.strftime('01/%m/%Y')
    
    # Business indicator
    if 'business indicator' in df.columns:
        df['Sampling'] = df['business indicator'].apply(lambda x: 1 if 'Sampling Rate' in str(x) else 0)
    
    # Supprimer les colonnes inutiles
    df = df.drop(columns=['content origin'], errors='ignore')
    
    # Traitement des attributs
    predefined_attributes = [
        'Composition', 'Efficiency', 'Packaging', 'Price',
        'Quality', 'Safety', 'Scent', 'Taste', 'Texture'
    ]
    
    attribute_columns = {attr: f"attribute_{attr}" for attr in predefined_attributes}
    for col_name in attribute_columns.values():
        df[col_name] = '0'
    
    # Traitement des attributs par ligne
    pos_attributes_by_row = {}
    neg_attributes_by_row = {}
    all_attributes_by_row = {}
    
    for idx, row in df.iterrows():
        pos_attrs_set = set()
        neg_attrs_set = set()
        all_attrs_set = set()
        
        # Traitement des attributs (tous)
        if pd.notna(row.get('attributes')):
            try:
                all_attrs = ast.literal_eval(row['attributes'])
                all_attrs_set = {attr for attr in all_attrs if attr in predefined_attributes}
            except (ValueError, SyntaxError):
                pass
        
        # Traitement des attributs positifs
        if pd.notna(row.get('attributes positive')):
            try:
                pos_attrs = ast.literal_eval(row['attributes positive'])
                pos_attrs_set = {attr for attr in pos_attrs if attr in predefined_attributes}
            except (ValueError, SyntaxError):
                pass
        
        # Traitement des attributs négatifs
        if pd.notna(row.get('attributes negative')):
            try:
                neg_attrs = ast.literal_eval(row['attributes negative'])
                neg_attrs_set = {attr for attr in neg_attrs if attr in predefined_attributes}
            except (ValueError, SyntaxError):
                pass
        
        pos_attributes_by_row[idx] = pos_attrs_set
        neg_attributes_by_row[idx] = neg_attrs_set
        all_attributes_by_row[idx] = all_attrs_set
    
    # Attribution des valeurs d'attributs
    for idx in all_attributes_by_row:
        all_attrs = all_attributes_by_row[idx]
        pos_attrs = pos_attributes_by_row[idx]
        neg_attrs = neg_attributes_by_row[idx]
        neutral_attrs = pos_attrs.intersection(neg_attrs)
        only_pos_attrs = pos_attrs - neutral_attrs
        only_neg_attrs = neg_attrs - neutral_attrs
        implicit_neutral_attrs = all_attrs - pos_attrs - neg_attrs
        
        for attr in neutral_attrs:
            df.at[idx, attribute_columns[attr]] = 'neutre'
        for attr in only_pos_attrs:
            df.at[idx, attribute_columns[attr]] = 'positive'
        for attr in only_neg_attrs:
            df.at[idx, attribute_columns[attr]] = 'negative'
        for attr in implicit_neutral_attrs:
            df.at[idx, attribute_columns[attr]] = 'neutre'
    
    # Colonne safety spéciale
    df['safety'] = '0'
    for idx in all_attributes_by_row:
        pos_attrs = pos_attributes_by_row[idx]
        neg_attrs = neg_attributes_by_row[idx]
        all_attrs = all_attributes_by_row[idx]
        safety_attrs = {'Safety', 'Composition'}
        safety_neutral = any(attr in (all_attrs - pos_attrs - neg_attrs) for attr in safety_attrs)
        safety_positive = any(attr in pos_attrs for attr in safety_attrs)
        safety_negative = any(attr in neg_attrs for attr in safety_attrs)
        
        if safety_positive and safety_negative:
            df.at[idx, 'safety'] = 'neutre'
        elif safety_positive:
            df.at[idx, 'safety'] = 'positive'
        elif safety_negative:
            df.at[idx, 'safety'] = 'negative'
        elif safety_neutral:
            df.at[idx, 'safety'] = 'neutre'
    
    # Sélectionner les colonnes finales
    original_columns = [col for col in df.columns if col not in ['attributes', 'attributes positive', 'attributes negative']]
    original_columns = [col for col in original_columns if not col.startswith('attribute_')]
    
    final_columns = original_columns + list(attribute_columns.values()) + ['safety']
    available_columns = [col for col in final_columns if col in df.columns]
    
    return df[available_columns]


def display_quotas():
    """Affiche les quotas API"""
    from api_client import api_client
    
    result = api_client.get_quotas()
    if result:
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Volume utilisé", result.get('used volume', 'N/A'))
        with col2:
            st.metric("Volume restant", result.get('remaining volume', 'N/A'))
        with col3:
            st.metric("Quota total", result.get('quota', 'N/A'))
        with col4:
            st.metric("Valable jusqu'au", result.get('end date', 'N/A'))


def create_excel_download(df, sheet_name='Data'):
    """Crée un fichier Excel pour téléchargement (avec gestion d'erreur)"""
    if not EXCEL_AVAILABLE:
        st.warning("⚠️ openpyxl non installé. Export Excel non disponible.")
        return None
    
    try:
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name=sheet_name)
        return excel_buffer.getvalue()
    except Exception as e:
        st.error(f"❌ Erreur lors de la création du fichier Excel : {e}")
        return None


def display_download_buttons(df, filename_base, mode="page", page=None):
    """Affiche les boutons de téléchargement avec gestion des erreurs"""
    
    # Génération des noms de fichiers
    csv_filename = f"{filename_base}_{mode}.csv"
    excel_filename = f"{filename_base}_{mode}.xlsx"
    
    if page is not None:
        csv_filename = f"{filename_base}_page{page}.csv"
        excel_filename = f"{filename_base}_page{page}.xlsx"
    
    # Colonnes pour les boutons
    if EXCEL_AVAILABLE:
        col1, col2, col3 = st.columns(3)
    else:
        col1, col2 = st.columns(2)
    
    # CSV (toujours disponible)
    with col1:
        csv_data = df.to_csv(index=False, encoding="utf-8-sig")
        st.download_button(
            "📂 Télécharger CSV",
            csv_data,
            file_name=csv_filename,
            mime="text/csv"
        )
    
    # Excel (conditionnel)
    if EXCEL_AVAILABLE:
        with col2:
            excel_data = create_excel_download(df)
            if excel_data:
                st.download_button(
                    "📄 Télécharger Excel",
                    excel_data,
                    file_name=excel_filename,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
        
        # Format plat
        with col3:
            try:
                df_flat = postprocess_reviews(df.copy())
                flat_csv = df_flat.to_csv(index=False, sep=';', encoding='utf-8-sig')
                flat_filename = f"{filename_base}_{mode}_plat.csv"
                if page is not None:
                    flat_filename = f"{filename_base}_page{page}_plat.csv"
                
                st.download_button(
                    "📃 Format plat",
                    flat_csv,
                    file_name=flat_filename,
                    mime="text/csv"
                )
            except Exception as e:
                st.warning(f"Erreur format plat : {e}")
    else:
        # Si Excel pas disponible, mettre le format plat à la place
        with col2:
            try:
                df_flat = postprocess_reviews(df.copy())
                flat_csv = df_flat.to_csv(index=False, sep=';', encoding='utf-8-sig')
                flat_filename = f"{filename_base}_{mode}_plat.csv"
                if page is not None:
                    flat_filename = f"{filename_base}_page{page}_plat.csv"
                
                st.download_button(
                    "📃 Format plat",
                    flat_csv,
                    file_name=flat_filename,
                    mime="text/csv"
                )
            except Exception as e:
                st.warning(f"Erreur format plat : {e}")


def display_excel_warning():
    """Affiche un avertissement si Excel n'est pas disponible"""
    if not EXCEL_AVAILABLE:
        st.warning("""
        ⚠️ **Export Excel non disponible**
        
        Le package `openpyxl` n'est pas installé. Pour activer l'export Excel :
        ```bash
        pip install openpyxl
        ```
        
        En attendant, vous pouvez utiliser les formats CSV et plat.
        """)


def log_export_activity(export_params, nb_reviews, export_type="STANDARD"):
    """Enregistre l'activité d'export dans un fichier log"""
    try:
        log_path = Path("review_exports_log.csv")
        export_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        log_entry = {
            "product": export_params.get("product", "BULK_EXPORT" if export_type == "BULK" else ""),
            "brand": export_params.get("brand", ""),
            "start_date": export_params.get("start-date"),
            "end_date": export_params.get("end-date"),
            "country": export_params.get("country", "Tous"),
            "rows": export_params.get("rows", 100),
            "random_seed": export_params.get("random", None),
            "nb_reviews": nb_reviews,
            "export_timestamp": export_date,
            "export_type": export_type
        }
        
        new_log_df = pd.DataFrame([log_entry])
        
        if log_path.exists():
            existing_log_df = pd.read_csv(log_path)
            log_df = pd.concat([existing_log_df, new_log_df], ignore_index=True)
        else:
            log_df = new_log_df
        
        log_df.to_csv(log_path, index=False)
        st.success(f"📝 Export {export_type} enregistré dans le journal")
        
    except Exception as e:
        st.warning(f"⚠️ Erreur lors de l'enregistrement du log : {str(e)}")
    """Enregistre l'activité d'export dans un fichier log"""
    try:
        log_path = Path("review_exports_log.csv")
        export_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        log_entry = {
            "product": export_params.get("product", "BULK_EXPORT" if export_type == "BULK" else ""),
            "brand": export_params.get("brand", ""),
            "start_date": export_params.get("start-date"),
            "end_date": export_params.get("end-date"),
            "country": export_params.get("country", "Tous"),
            "rows": export_params.get("rows", 100),
            "random_seed": export_params.get("random", None),
            "nb_reviews": nb_reviews,
            "export_timestamp": export_date,
            "export_type": export_type
        }
        
        new_log_df = pd.DataFrame([log_entry])
        
        if log_path.exists():
            existing_log_df = pd.read_csv(log_path)
            log_df = pd.concat([existing_log_df, new_log_df], ignore_index=True)
        else:
            log_df = new_log_df
        
        log_df.to_csv(log_path, index=False)
        st.success(f"📝 Export {export_type} enregistré dans le journal")
        
    except Exception as e:
        st.warning(f"⚠️ Erreur lors de l'enregistrement du log : {str(e)}")
