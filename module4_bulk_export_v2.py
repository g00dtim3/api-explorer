"""
Module 4 - Bulk Export V2
Export traçable, reprenable et vérifiable (jusqu'à 500 000 mentions).

Tout l'état affiché est relu dans Supabase : recharger la page ne perd rien.
Le travail tourne dans une tâche de fond de l'application (bulk_export.runner), pas dans le navigateur.
Documentation : docs/bulk_v2/EXECUTION.md
"""

from __future__ import annotations

import datetime as dt
import json

import pandas as pd
import streamlit as st

from bulk_export import db, downloads, finalize, rehydrate, state_store as ss, ui_logic
from bulk_export.api_adapter import RatingsReviewsAdapter
from bulk_export.api_http import ApiError, RatingsReviewsHttpClient
from bulk_export.logging_utils import mask
from bulk_export.models import ALLOWED_BATCH_SIZES, DEFAULT_BATCH_SIZE, ConfigError, ExportConfig
from bulk_export.runner import build_runner
from bulk_export.settings import SettingsError, load_api_credentials, load_settings
from bulk_export.storage import StorageError, build_storage
from charte import badge_statut, encadre_cle, etapes, libelle_statut, section, vide
from utils import format_nombre

LIMIT_TITLE = "Limite de la version 1"
LIMIT_TEXT = (
    "L'export avance tant que l'application Streamlit est en marche. Fermer l'onglet "
    "ne l'arrête pas nécessairement, mais un redémarrage, un redéploiement ou une mise en veille de l'application "
    "l'interrompt. Dans ce cas, aucune donnée validée n'est perdue : l'export reprend au dernier point de reprise "
    "quand on clique sur « Reprendre »."
)
TAB_NEW, TAB_MONITOR, TAB_DOWNLOADS, TAB_HISTORY = "Nouvel export", "Suivi", "Téléchargements", "Historique"
TAB_ICONS = {TAB_NEW: "add_circle", TAB_MONITOR: "monitoring", TAB_DOWNLOADS: "download", TAB_HISTORY: "history"}
REFRESH_S = 5
_LEVEL_STYLE = {"ERROR": st.error, "WARNING": st.warning}


# ─── Ressources partagées ─────────────────────────────────────────────────────

@st.cache_resource(show_spinner=False)
def get_runner():
    """Un seul gestionnaire d'exécution par application (partagé entre les onglets et les utilisateurs)."""
    return build_runner(load_settings(), load_api_credentials())


def _connect():
    return db.connect(load_settings(), attempts=1)


def _storage():
    """Stockage des fichiers finaux, ou None s'il n'est pas configuré."""
    settings = load_settings()
    if not (settings.supabase_url and settings.supabase_service_key):
        return None
    return build_storage(settings)


def _http() -> RatingsReviewsHttpClient:
    creds = load_api_credentials()
    return RatingsReviewsHttpClient(creds.token, base_url=creds.base_url)


@st.cache_data(ttl=3600, show_spinner=False)
def _list(endpoint: str, params: tuple = ()) -> dict:
    """Listes de référence (marques, pays…), via le client strict : le token n'est jamais affiché."""
    try:
        return _http().get(endpoint, dict(params)).payload["result"]
    except (ApiError, SettingsError) as exc:
        st.warning(mask(f"Liste {endpoint} indisponible : {exc}"), icon=":material/warning:")
        return {}


# ─── Onglet Nouvel export ─────────────────────────────────────────────────────

def _filters_form() -> dict[str, str]:
    c1, c2 = st.columns(2)
    start = c1.date_input("Date de début", value=dt.date(2022, 1, 1), key="bv2_start")
    end = c2.date_input("Date de fin", value=dt.date.today(), key="bv2_end")

    categories = _list("/categories").get("categories", [])
    category = c1.selectbox("Catégorie", ["ALL"] + [c["category"] for c in categories], key="bv2_category")
    subs = ["ALL"] + next((c.get("subcategories", []) for c in categories if c["category"] == category), [])
    subcategory = c2.selectbox("Sous-catégorie", subs, key="bv2_subcategory")

    brand_params = tuple((k, v) for k, v in (("category", category), ("subcategory", subcategory)) if v != "ALL")
    brands = st.multiselect("Marques", _list("/brands", brand_params).get("brands", []), key="bv2_brands")
    countries = c1.multiselect("Pays", ["ALL"] + _list("/countries").get("countries", []), key="bv2_countries")
    source_params = (("country", countries[0]),) if countries and countries[0] != "ALL" else ()
    sources = c2.multiselect("Sources", ["ALL"] + _list("/sources", source_params).get("sources", []),
                             key="bv2_sources")
    markets = c1.multiselect("Markets", ["ALL"] + _list("/markets").get("markets", []), key="bv2_markets")
    attr_options = _list("/attributes", brand_params).get("attributes", [])
    with st.expander("Attributs (optionnel)"):
        attributes = st.multiselect("Attributs", attr_options, key="bv2_attr")
        attr_pos = st.multiselect("Attributs positifs", attr_options, key="bv2_attr_pos")
        attr_neg = st.multiselect("Attributs négatifs", attr_options, key="bv2_attr_neg")
    return ui_logic.form_to_filters(
        start_date=start, end_date=end, category=category, subcategory=subcategory, brands=brands,
        countries=countries, sources=sources, markets=markets, attributes=attributes,
        attributes_positive=attr_pos, attributes_negative=attr_neg)


def _import_block() -> dict[str, str] | None:
    text = st.text_area("Collez une configuration JSON (Bulk Export V2, ou ancien format des modules 1 à 3)",
                        height=160, key="bv2_import_text")
    if st.button("Charger la configuration", key="bv2_import_btn", icon=":material/upload_file:"):
        try:
            imported = ui_logic.parse_import_json(text)
        except (ValueError, ConfigError) as exc:
            st.error(f"Configuration refusée : {exc}", icon=":material/error:")
            return None
        st.session_state["bv2_imported"] = {"filters": imported.filters, "options": imported.options,
                                            "warnings": imported.warnings, "format": imported.source_format}
    imported = st.session_state.get("bv2_imported")
    if not imported:
        return None
    for w in imported["warnings"]:
        st.warning(w, icon=":material/warning:")
    st.caption(f"Configuration importée (format {imported['format']}) :")
    st.json(imported["filters"])
    if st.button("Oublier cette configuration", key="bv2_import_clear"):
        st.session_state.pop("bv2_imported", None)
        st.rerun()
    return dict(imported["filters"])


def _new_export_tab(conn, runner, runner_error: str | None) -> None:
    progression = st.empty()  # étapes du parcours, remplies une fois la configuration et l'estimation connues

    with section("Configuration d'export", "Choisissez les filtres, les formats et le nom de l'export."):
        st.session_state.setdefault("bv2_source", "Formulaire")
        source = st.segmented_control("Source des filtres", ["Formulaire", "Import JSON"], required=True,
                                      key="bv2_source")
        filters = _filters_form() if source == "Formulaire" else _import_block()
        imported_options = (st.session_state.get("bv2_imported") or {}).get("options", {}) if source != "Formulaire" else {}

        c1, c2, c3 = st.columns(3)
        mode = c1.radio("Mode d'export", ["Complet", "Aperçu (100 mentions)"], key="bv2_mode")
        all_formats = ["csv", "jsonl", "zip", "xlsx", "plat"]
        formats = c2.multiselect("Formats de sortie", all_formats,
                                 default=list(imported_options.get("output_formats", all_formats)),
                                 format_func={"csv": "CSV UTF-8", "jsonl": "JSONL", "zip": "Archive ZIP", "xlsx": "Excel",
                                              "plat": "Fichier plat (;)"}.get,
                                 key="bv2_formats")
        default_batch = imported_options.get("batch_size", DEFAULT_BATCH_SIZE)
        batch_size = c3.radio("Taille des lots enregistrés", ALLOWED_BATCH_SIZES,
                              index=ALLOWED_BATCH_SIZES.index(default_batch),
                              format_func=lambda n: f"{format_nombre(n)} mentions"
                              + (" — recommandé" if n == DEFAULT_BATCH_SIZE else ""), key="bv2_batch")
        name = st.text_input("Nom de l'export", value=imported_options.get("name")
                             or (ui_logic.default_name(filters) if filters else ""), key="bv2_name")

        config, config_error = None, None
        if filters is not None:
            try:
                config = ExportConfig(name=name, filters=filters, output_formats=tuple(formats), batch_size=batch_size,
                                      fingerprint=imported_options.get("fingerprint", {}),
                                      pagination=imported_options.get("pagination", {}))
            except ConfigError as exc:
                config_error = str(exc)
        if config is not None:
            st.download_button("Exporter cette configuration (JSON)", json.dumps(config.to_dict(), indent=2,
                               ensure_ascii=False), file_name="config_bulk_export_v2.json", mime="application/json",
                               icon=":material/download:")

    # — Estimation —
    with section("Estimation du volume", "Nombre de mentions annoncé par l'API, avant tout lancement."):
        with st.container(horizontal=True):
            estimate_clicked = st.button("Estimer le volume", disabled=config is None or runner is None,
                                         key="bv2_estimate_btn", icon=":material/calculate:")
            quota_clicked = st.button("Voir les quotas", disabled=runner is None, key="bv2_quota",
                                      icon=":material/data_usage:")
        if estimate_clicked:
            try:
                adapter = RatingsReviewsAdapter(_http(), config.filters, rows=config.rows)
                measures = ui_logic.read_measures(conn) if conn is not None else None
                st.session_state["bv2_estimate"] = ui_logic.compute_estimate(config, adapter.expected_count(), measures)
            except (ApiError, SettingsError) as exc:
                st.error(mask(f"Estimation impossible : {exc}. Vérifiez les filtres, puis estimez à nouveau."),
                         icon=":material/error:")
        if quota_clicked:
            quota = RatingsReviewsAdapter(_http(), {}).quota()
            if quota:
                st.json(quota)
            else:
                st.info("Quotas non disponibles.", icon=":material/info:")

        estimate = st.session_state.get("bv2_estimate")
        estimate_ok = estimate is not None and config is not None and estimate.config_hash == config.config_hash
        if estimate_ok:
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Mentions (API /metrics)", format_nombre(estimate.expected), border=True)
            m2.metric("Pages API", format_nombre(estimate.pages), border=True)
            m3.metric("Lots", format_nombre(estimate.batches), border=True)
            m4.metric("Durée indicative", ui_logic.format_duration(estimate.seconds)
                      if estimate.seconds is not None else "—", border=True)
            if estimate.raw_bytes is not None:
                st.caption(f"Espace indicatif pendant la collecte : {ui_logic.format_bytes(estimate.raw_bytes)} "
                           "de JSON brut (hors index), mesuré sur les exports réels précédents.")
            if estimate.seconds is None and estimate.raw_bytes is None:
                st.caption("Durée et espace : pas encore de mesure réelle (elles apparaîtront après un premier export).")
        elif estimate is not None:
            st.caption("Les filtres ont changé depuis la dernière estimation : estimez à nouveau.")

    with progression:
        etapes(["Configurer", "Estimer", "Lancer"], courante=0 if config is None else (2 if estimate_ok else 1))

    # — Lancement —
    with section("Lancement"):
        if mode.startswith("Aperçu"):
            if st.button("Afficher l'aperçu", disabled=config is None or runner is None, type="primary",
                         key="bv2_preview", icon=":material/visibility:"):
                _preview(config)
            return

        active = ss.active_export_id(conn) if conn is not None else None
        blockers = ui_logic.launch_blockers(config=config, config_error=config_error, estimate=estimate,
                                            active_export=active, db_ok=conn is not None, runner_ok=runner is not None)
        if runner_error:
            st.error(runner_error, icon=":material/error:")
        for w in ui_logic.launch_warnings(estimate):
            st.warning(w, icon=":material/warning:")
        for reason in blockers:
            st.info(reason, icon=":material/lock:")
        if st.button("Lancer l'export", type="primary", disabled=bool(blockers), key="bv2_launch",
                     icon=":material/play_arrow:"):
            export_id = ss.create_export(conn, config, expected_count=estimate.expected)
            result = runner.start(export_id)
            if result.ok:
                st.session_state["bv2_selected"] = export_id
                st.session_state["bv2_goto"] = TAB_MONITOR  # appliqué au début de l'exécution suivante
                st.rerun()
            st.error(result.message, icon=":material/error:")


def _preview(config: ExportConfig) -> None:
    try:
        adapter = RatingsReviewsAdapter(_http(), config.filters, rows=100)
        page = adapter.fetch_page(adapter.initial_cursor())
    except Exception as exc:  # erreur API, pagination ou paramètres : affichée sans secret
        st.error(mask(f"Aperçu impossible : {exc}. Vérifiez les filtres, puis réessayez."), icon=":material/error:")
        return
    st.success(f"Aperçu : {len(page.records)} mentions (rien n'est enregistré).", icon=":material/check_circle:")
    if page.records:
        st.caption("Champs reçus : " + ", ".join(sorted({k for r in page.records for k in r})))
        # Affichage seulement : conversion en texte pour le tableau, les données ne sont pas conservées.
        st.dataframe(pd.DataFrame(page.records).astype(str), use_container_width=True)


# ─── Onglet Suivi ─────────────────────────────────────────────────────────────

def _monitor_tab(conn, runner) -> None:
    exports = ss.list_exports(conn, limit=50)
    if not exports:
        vide("Aucun export pour l'instant. Créez-en un dans l'onglet « Nouvel export ».")
        return
    active = ss.active_export_id(conn)
    default = ui_logic.choose_export(exports, active, st.session_state.get("bv2_selected"))
    ids = [e["export_id"] for e in exports]
    labels = {e["export_id"]: f"{e['name']} — {libelle_statut(e['status'])} ({e['export_id']})" for e in exports}
    export_id = st.selectbox("Export", ids, index=ids.index(default), format_func=labels.get, key="bv2_monitor_sel")
    st.session_state["bv2_selected"] = export_id

    status = next(e["status"] for e in exports if e["export_id"] == export_id)
    live = status in ("RUNNING", "STOPPING", "PENDING", "VALIDATING")
    if live and hasattr(st, "fragment"):
        st.fragment(run_every=REFRESH_S)(_monitor_block)(export_id, runner)
    else:
        if live:
            st.button("Rafraîchir", key="bv2_refresh", icon=":material/refresh:")
        _monitor_block(export_id, runner)


def _monitor_block(export_id: str, runner) -> None:
    try:
        conn = _connect()
    except Exception as exc:
        st.error(mask(f"Connexion à Supabase impossible : {exc}. Rechargez la page dans un instant."),
                 icon=":material/error:")
        return
    try:
        row = ss.get_export(conn, export_id)
        now = conn.execute("SELECT now()").fetchone()[0]
        if ui_logic.is_orphan(row, now):
            ss.recover_orphans(conn)
            row = ss.get_export(conn, export_id)
        files = ss.list_files(conn, export_id)
        with section(row["name"]):
            _indicators(row, now, files)
            _controls(row, runner)
        if row["validation_json"]:
            with section("Validation", "Contrôles qualité faits avant de déclarer l'export terminé."):
                _validation_results(row)
        with section("Journal", "Les 20 derniers événements de l'export."):
            _events(conn, export_id)
    finally:
        conn.close()


def _indicators(row, now, files) -> None:
    status = row["status"]
    st.markdown(f"{badge_statut(status)} `{row['export_id']}`")
    fraction, gap = ui_logic.progress(row["unique_count"], row["expected_count"])
    st.progress(fraction, text=f"{fraction:.0%} des mentions attendues".replace("%", "\u00a0%")
                + (f" (écart : {gap:+,})".replace(",", "\u00a0") if gap else ""))
    end = row["finished_at"] or (now if status in ("RUNNING", "STOPPING") else row["last_updated_at"])
    cols = st.columns(5)
    cols[0].metric("Attendues", format_nombre(row["expected_count"]) if row["expected_count"] is not None else "—",
                   border=True)
    cols[1].metric("Reçues", format_nombre(row["retrieved_count"]), border=True)
    cols[2].metric("Uniques", format_nombre(row["unique_count"]), border=True)
    cols[3].metric("Pages API", format_nombre(row["pages_count"]), border=True)
    cols[4].metric("Durée écoulée", ui_logic.format_duration((end - row["created_at"]).total_seconds()), border=True)
    cols = st.columns(5)
    cols[0].metric("Doublons", format_nombre(row["duplicate_count"]), border=True)
    cols[1].metric("Jumelles", format_nombre(row["collision_count"]), border=True)
    cols[2].metric("Rejetées", format_nombre(row["error_count"]), border=True)
    cols[3].metric("Lots (fichiers)", format_nombre(sum(1 for f in files if f["kind"] == "batch_jsonl")), border=True)
    cols[4].metric("Quota API", "illimité", border=True)
    st.caption(f"Point de reprise : `{row['last_committed_cursor'] or 'début'}` — "
               f"pagination terminée : {'oui' if row['pagination_finished'] else 'non'}")
    if row["collision_count"]:
        st.warning(f"{row['collision_count']} avis jumeaux détectés : tous gardés, tracés dans le journal des conflits.",
                   icon=":material/warning:")
    if row["error_count"]:
        st.warning(f"{row['error_count']} mention(s) rejetée(s) (ex. sans date), gardées à part : l'export ne peut pas "
                   "être déclaré terminé tant qu'elles existent.", icon=":material/warning:")
    if status == "FAILED" and row["error_details"]:
        st.error(f"Échec : {row['error_details'].get('message', '')}. L'export peut reprendre au dernier point "
                 "de reprise : cliquez sur « Reprendre ».", icon=":material/error:")
    if status == "INCOMPLETE" and row["pagination_finished"] and not row["validation_json"]:
        st.info("Collecte terminée, validation à lancer : l'export n'est pas encore déclaré complet.",
                icon=":material/info:")
    if status == "VALIDATING":
        st.info("Validation en cours : fabrication des fichiers, envoi dans Storage, relecture et contrôles…",
                icon=":material/sync:")
    if status == "COMPLETED":
        st.success(f"Export terminé : complet et validé. Fichiers dans l'onglet « {TAB_DOWNLOADS} ».",
                   icon=":material/check_circle:")


def _controls(row, runner) -> None:
    status, export_id = row["status"], row["export_id"]
    # Une seule action principale visible à la fois : Arrêter, Valider ou Reprendre (états exclusifs).
    if status in ("RUNNING", "PENDING"):
        if st.button("Arrêter après la page en cours", type="primary", key=f"bv2_stop_{export_id}",
                     icon=":material/stop_circle:"):
            if runner is not None:
                runner.request_stop(export_id)
            st.info("Arrêt demandé : l'export se met en pause après la page en cours.", icon=":material/info:")
    if status == "STOPPING" or (status == "RUNNING" and row["stop_requested"]):
        st.info("Arrêt en cours…", icon=":material/sync:")
    finished = bool(row["pagination_finished"])
    if finished and status in ("INCOMPLETE", "FAILED"):
        if st.button("Valider l'export", type="primary", disabled=runner is None, key=f"bv2_validate_{export_id}",
                     icon=":material/fact_check:"):
            result = runner.validate(export_id)
            if result.ok:
                st.rerun()
            st.error(result.message, icon=":material/error:")
        return
    resumable = status in ("PAUSED", "FAILED") or (status == "INCOMPLETE" and not finished)
    if resumable:
        if status == "PAUSED" and row["error_details"] is None:
            st.info("Export en pause : il reprendra au dernier point de reprise, sans perte ni doublon.",
                    icon=":material/pause_circle:")
        if st.button("Reprendre l'export", type="primary", disabled=runner is None, key=f"bv2_resume_{export_id}",
                     icon=":material/play_arrow:"):
            result = runner.start(export_id)
            if result.ok:
                st.rerun()
            st.error(result.message, icon=":material/error:")


def _validation_results(row) -> None:
    result = row["validation_json"]
    if not result:
        return
    st.markdown(f"{badge_statut(result.get('final_status'))} Validation du {result.get('validated_at', '')}")
    verdicts = {True: "Réussi", False: "Échec", None: "Information"}
    st.dataframe(pd.DataFrame([{"Résultat": verdicts[c["ok"]], "Contrôle": c["name"], "Détail": c["detail"],
                                "Si échec": c["on_fail"] or "—"} for c in result.get("checks", [])]),
                 use_container_width=True, hide_index=True)


def _events(conn, export_id: str) -> None:
    for event in ss.list_events(conn, export_id, limit=20):
        text = f"{event['created_at']:%d/%m %H:%M:%S} — {event['message']}"
        _LEVEL_STYLE.get(event["level"], st.text)(text)


# ─── Onglets Téléchargements et Historique ────────────────────────────────────

_FILE_LABELS = {"csv_complete": "CSV complet", "xlsx": "Excel", "csv_plat": "Fichier plat (;)",
                "zip": "Archive ZIP (lots + manifeste)", "manifest": "Manifeste (JSON)",
                "csv_partial": "CSV — DONNÉES PARTIELLES"}


def _link(storage, f, expires_s: int = 3600) -> None:
    name = f["path"].rsplit("/", 1)[-1]
    try:
        url = storage.signed_url(f["path"], expires_s, download_name=name)
    except StorageError as exc:
        st.error(mask(str(exc)), icon=":material/error:")
        return
    size = ui_logic.format_bytes(f["size_bytes"])
    st.link_button(f"{_FILE_LABELS.get(f['kind'], name)} — {size}", url, icon=":material/download:")


def _downloads_tab(conn) -> None:
    storage = _storage()
    if storage is None:
        st.warning("Stockage non configuré : renseignez supabase_url et supabase_service_key (LISEZMOI §1.5).",
                   icon=":material/warning:")
        return
    done = [e for e in ss.list_exports(conn, limit=200) if e["status"] == "COMPLETED" and not e["files_expired_at"]]
    if not done:
        vide("Aucun export terminé avec des fichiers disponibles. Un export apparaît ici une fois validé.")
        return
    labels = {e["export_id"]: f"{e['name']} — {format_nombre(e['unique_count'])} mentions ({e['export_id']})"
              for e in done}
    export_id = st.selectbox("Export validé", list(labels), format_func=labels.get, key="bv2_dl_sel")
    files = ss.list_files(conn, export_id)
    st.caption("Liens signés valables 1 heure. Le téléchargement se fait directement depuis Supabase Storage "
               "(aucun appel à l'API Ratings & Reviews, aucun chargement dans l'application).")
    for kind in ("csv_complete", "xlsx", "csv_plat", "zip", "manifest"):
        for f in files:
            if f["kind"] == kind:
                _link(storage, f)
    batches = [f for f in files if f["kind"] == "batch_jsonl"]
    with st.expander(f"Lots JSONL compressés ({len(batches)}) — référence brute"):
        if st.button("Générer les liens des lots", key=f"bv2_dl_batches_{export_id}", icon=":material/link:"):
            for f in batches:
                _link(storage, f)


def _space_header(conn) -> None:
    """Place occupée par la base et par le brut conservé (lot 1A), avec un avertissement au-delà du seuil."""
    try:
        sizes = ss.database_sizes(conn)
        threshold = load_settings().alerte_taille_base_go
    except Exception as exc:
        st.caption(mask(f"Taille de la base indisponible : {exc}"))
        return
    c1, c2 = st.columns(2)
    c1.metric("Taille de la base (tous schémas)", ui_logic.format_bytes(sizes["database"]), border=True)
    c2.metric("Mentions brutes conservées en base", ui_logic.format_bytes(sizes["raw_mentions"]), border=True)
    warning = ui_logic.size_warning(sizes["database"], threshold)
    if warning:
        st.warning(warning, icon=":material/warning:")


def _history_tab(conn, runner) -> None:
    with section("Espace occupé"):
        _space_header(conn)
    exports = ss.list_exports(conn, limit=200)
    if not exports:
        vide("Aucun export pour l'instant. Créez-en un dans l'onglet « Nouvel export ».")
        return
    with section("Exports", "Tous les exports, du plus récent au plus ancien."):
        _history_table(exports)
    with section("Actions sur un export", "Reprendre, valider, générer un fichier partiel ou supprimer."):
        _history_actions(conn, runner, exports)


def _history_table(exports) -> None:
    table = [{"Nom": e["name"], "Statut": libelle_statut(e["status"]), "Attendues": e["expected_count"], "Uniques": e["unique_count"],
              "Doublons": e["duplicate_count"], "Rejetées": e["error_count"], "Créé le": e["created_at"],
              "Fini le": e["finished_at"],
              "Brut en base": ui_logic.raw_status(e),
              "Fichiers": "expirés" if e["files_expired_at"] else "",
              "Filtres": json.dumps(e["config_json"].get("filters", {}), ensure_ascii=False),
              "Export ID": e["export_id"]} for e in exports]
    number = st.column_config.NumberColumn(format="localized")
    date = st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm")
    st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True,
                 column_config={"Attendues": number, "Uniques": number, "Doublons": number, "Rejetées": number,
                                "Créé le": date, "Fini le": date})


def _history_actions(conn, runner, exports) -> None:
    labels = {e["export_id"]: f"{e['name']} — {libelle_statut(e['status'])} ({e['export_id']})" for e in exports}
    export_id = st.selectbox("Actions sur l'export", list(labels), format_func=labels.get, key="bv2_hist_sel")
    row = ss.get_export(conn, export_id)
    status, finished = row["status"], row["pagination_finished"]
    st.markdown(badge_statut(status))
    c1, c2, c3 = st.columns(3)
    if status in ("PAUSED", "FAILED", "INCOMPLETE") and not finished:
        if c1.button("Reprendre l'export", key="bv2_hist_resume", disabled=runner is None, icon=":material/play_arrow:"):
            result = runner.start(export_id)
            _show_result(result)
    if status in ("INCOMPLETE", "FAILED") and finished:
        if c1.button("Valider l'export", key="bv2_hist_validate", disabled=runner is None, icon=":material/fact_check:"):
            result = runner.validate(export_id)
            _show_result(result)
    storage = _storage()
    if status != "COMPLETED" and row["unique_count"] and storage is not None:
        if c2.button("Générer un fichier partiel", key="bv2_hist_partial", icon=":material/description:"):
            _partial(conn, storage, export_id)
    for f in ss.list_files(conn, export_id):
        if f["kind"] == "csv_partial" and storage is not None:
            _link(storage, f)
    if status == "COMPLETED" and row["raw_purged_at"] and not row["files_expired_at"] and storage is not None:
        if c2.button("Réhydrater le brut", key=f"bv2_hist_rehydrate_{export_id}", icon=":material/restore:",
                     help="Remet les mentions brutes en base à partir des lots JSONL de Storage "
                          "(empreintes vérifiées). Peut prendre plusieurs minutes pour un gros export."):
            _rehydrate(conn, storage, export_id)

    with c3.popover("Supprimer…", icon=":material/delete:"):
        resumable = status in ("PENDING", "PAUSED", "FAILED", "INCOMPLETE")
        st.write("Supprime l'export, ses mentions en base et ses fichiers dans Storage. **Irréversible.**")
        sure = st.checkbox("Je confirme la suppression", key=f"bv2_del_ok_{export_id}")
        sure_resumable = True
        if resumable:
            sure_resumable = st.checkbox("Je sais que cet export est encore reprenable ou validable",
                                         key=f"bv2_del_ok2_{export_id}")
        if st.button("Supprimer définitivement", disabled=not (sure and sure_resumable), key=f"bv2_del_{export_id}",
                     icon=":material/delete_forever:"):
            try:
                finalize.delete_everywhere(conn, storage, export_id, confirm_resumable=resumable and sure_resumable)
                st.success("Export supprimé.", icon=":material/check_circle:")
                st.rerun()
            except (ss.StateError, StorageError) as exc:
                st.error(mask(str(exc)), icon=":material/error:")


def _show_result(result) -> None:
    if result.ok:
        st.success(result.message, icon=":material/check_circle:")
    else:
        st.error(result.message, icon=":material/error:")


def _rehydrate(conn, storage, export_id: str) -> None:
    with st.spinner("Réhydratation : relecture et vérification des lots…"):
        try:
            count = rehydrate.rehydrate(conn, export_id, storage)
        except (rehydrate.RehydrateError, ss.StateError) as exc:
            st.error(mask(str(exc)), icon=":material/error:")
            return
    st.success(f"Brut réhydraté : {format_nombre(count)} mentions remises en base.", icon=":material/check_circle:")


def _partial(conn, storage, export_id: str) -> None:
    import tempfile
    from pathlib import Path

    with st.spinner("Génération du fichier partiel…"), tempfile.TemporaryDirectory(prefix="bulk_partial_") as tmp:
        try:
            record = downloads.build_partial_csv(conn, export_id, storage, Path(tmp))
        except (StorageError, ss.StateError) as exc:
            st.error(mask(f"Génération impossible : {exc}. Réessayez dans un instant."), icon=":material/error:")
            return
    ss.replace_files(conn, export_id, [record], kinds=["csv_partial"])
    ss.add_event(conn, export_id, "WARNING", f"Fichier « DONNÉES PARTIELLES » généré ({record.rows_count} lignes).")
    st.success(f"Fichier partiel généré : {format_nombre(record.rows_count)} lignes, étiqueté « DONNÉES PARTIELLES ».",
               icon=":material/check_circle:")


# ─── Page ─────────────────────────────────────────────────────────────────────

def main():
    encadre_cle(LIMIT_TEXT, titre=LIMIT_TITLE)

    conn, runner, runner_error = None, None, None
    try:
        settings = load_settings()
        conn = _connect()
    except Exception as exc:
        st.error(mask(f"Connexion à Supabase impossible : {exc}. Vérifiez la section [bulk_export] des secrets "
                      "(docs/bulk_v2/LISEZMOI.md)."), icon=":material/error:")
        settings = None
    try:
        runner = get_runner()
    except Exception as exc:
        runner_error = mask(f"Moteur d'export indisponible : {exc}")
    if runner is not None and conn is not None:
        try:
            runner.recover(auto_resume=settings.auto_resume)
        except Exception as exc:
            st.warning(mask(f"Vérification des exports interrompus impossible : {exc}"), icon=":material/warning:")
    if conn is not None and settings is not None:
        try:
            storage = _storage()
            if storage is not None:
                finalize.apply_retention(conn, storage, settings.retention_days)
        except Exception as exc:
            st.warning(mask(f"Nettoyage des fichiers expirés impossible : {exc}"), icon=":material/warning:")

    # Bascule demandée (ex. après « Lancer ») : à faire AVANT d'afficher les widgets concernés.
    goto = st.session_state.pop("bv2_goto", None)
    if goto:
        st.session_state["bv2_tab"] = goto
        st.session_state.pop("bv2_monitor_sel", None)

    try:
        st.session_state.setdefault("bv2_tab", TAB_NEW)
        tab = st.segmented_control("Onglet", [TAB_NEW, TAB_MONITOR, TAB_DOWNLOADS, TAB_HISTORY], required=True, format_func=lambda t: f":material/{TAB_ICONS[t]}: {t}",
                                   key="bv2_tab", label_visibility="collapsed")
        if tab == TAB_NEW:
            _new_export_tab(conn, runner, runner_error)
        elif conn is None:
            st.error("Cet onglet a besoin de Supabase : vérifiez la section [bulk_export] des secrets, "
                     "puis rechargez la page.", icon=":material/error:")
        elif tab == TAB_MONITOR:
            _monitor_tab(conn, runner)
        elif tab == TAB_DOWNLOADS:
            _downloads_tab(conn)
        else:
            _history_tab(conn, runner)
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    # Lancement direct de ce fichier : même protection que l'application principale.
    from auth import exiger_mot_de_passe

    exiger_mot_de_passe()
    main()
