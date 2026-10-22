"""
Client API partagé pour l'explorateur Ratings & Reviews
"""
import streamlit as st
import requests
import urllib.parse
from functools import lru_cache

from bulk_export.logging_utils import mask, register_secret


class APIClient:
    def __init__(self):
        self.BASE_URL = "https://api-pf.ratingsandreviews-beauty.com"
        self.TOKEN = st.secrets["api"]["token"]
        register_secret(self.TOKEN)  # le token ne doit jamais apparaître dans un message (règle n°8)
    
    def _quote_strict(self, string, safe='/', encoding=None, errors=None):
        """Encodage strict des paramètres URL"""
        return urllib.parse.quote(string, safe='', encoding=encoding, errors=errors)
    
    @st.cache_data(ttl=3600)
    def _fetch_cached(_self, endpoint, params=None):
        """Fonction de base pour récupérer les données de l'API avec cache"""
        if params is None:
            params = {}
        elif isinstance(params, str):
            st.error("Paramètres invalides : `params` doit être un dict ou une liste de tuples, pas une chaîne.",
                     icon=":material/error:")
            return {}
        
        # Ajouter le token (sur une copie : le dictionnaire de l'appelant ne doit pas recevoir le token)
        if isinstance(params, dict):
            params = dict(params)
            params["token"] = _self.TOKEN
            query_string = urllib.parse.urlencode(params, doseq=True, quote_via=_self._quote_strict)
        else:
            params = list(params)
            params.append(("token", _self.TOKEN))
            query_string = urllib.parse.urlencode(params, doseq=True, quote_via=_self._quote_strict)
        
        url = f"{_self.BASE_URL}{endpoint}?{query_string}"
        
        try:
            response = requests.get(url, headers={"Accept": "application/json"})
            if response.status_code == 200:
                return response.json().get("result", {})
            else:
                # Adresse et réponse masquées : le token est dans l'adresse (règle n°8)
                st.error(mask(f"Erreur {response.status_code} sur {url}"), icon=":material/error:")
                st.error(mask(f"Réponse : {response.text}"))
                return {}
        except Exception as e:
            st.error(mask(f"Erreur de connexion : {str(e)}. Réessayez dans un instant."), icon=":material/error:")
            return {}
    
    def fetch(self, endpoint, params=None):
        """Wrapper pour la fonction fetch_cached"""
        return self._fetch_cached(endpoint, params)
    
    def get_quotas(self):
        """Récupère les quotas API"""
        return self.fetch("/quotas")
    
    def get_categories(self):
        """Récupère les catégories disponibles"""
        return self.fetch("/categories")
    
    def get_brands(self, category=None, subcategory=None):
        """Récupère les marques disponibles"""
        params = {}
        if category and category != "ALL":
            params["category"] = category
        if subcategory and subcategory != "ALL":
            params["subcategory"] = subcategory
        return self.fetch("/brands", params)
    
    def get_countries(self):
        """Récupère les pays disponibles"""
        return self.fetch("/countries")
    
    def get_sources(self, country=None):
        """Récupère les sources disponibles"""
        params = {}
        if country:
            params["country"] = country
        return self.fetch("/sources", params)
    
    def get_markets(self):
        """Récupère les markets disponibles"""
        return self.fetch("/markets")
    
    def get_ratings(self):
        """Récupère la liste des valeurs de rating disponibles"""
        return self.fetch("/ratings")
    
    def get_attributes(self, category=None, subcategory=None, brand=None):
        """Récupère les attributs dynamiquement selon les filtres"""
        params = {}
        if category and category != "ALL":
            params["category"] = category
        if subcategory and subcategory != "ALL":
            params["subcategory"] = subcategory
        if brand:
            params["brand"] = ",".join(brand) if isinstance(brand, list) else brand
        return self.fetch("/attributes", params)
    
    def get_products(self, brand, category=None, subcategory=None, start_date=None, end_date=None, **kwargs):
        """Récupère les produits pour une marque donnée"""
        params = {"brand": brand}
        
        if start_date:
            params["start-date"] = start_date
        if end_date:
            params["end-date"] = end_date
        if category and category != "ALL":
            params["category"] = category
        if subcategory and subcategory != "ALL":
            params["subcategory"] = subcategory
        
        # Ajouter les autres filtres
        for key, value in kwargs.items():
            if value and value != "ALL":
                if isinstance(value, list):
                    params[key] = ",".join(value)
                else:
                    params[key] = value
        
        return self.fetch("/products", params)
    
    def get_metrics(self, **params):
        """Récupère les métriques pour une combinaison de filtres"""
        clean_params = {}
        for key, value in params.items():
            if value and value != "ALL":
                if isinstance(value, list) and value:
                    clean_params[key] = ",".join(str(v) for v in value)
                elif not isinstance(value, list):
                    clean_params[key] = str(value)
        
        return self.fetch("/metrics", clean_params)
    
    def get_reviews(self, **params):
        """Récupère les reviews pour une combinaison de filtres"""
        clean_params = {}
        for key, value in params.items():
            if value and value != "ALL":
                if isinstance(value, list) and value:
                    clean_params[key] = ",".join(str(v) for v in value)
                elif not isinstance(value, list):
                    clean_params[key] = str(value)
        
        return self.fetch("/reviews", clean_params)


# Instance globale du client API
api_client = APIClient()
