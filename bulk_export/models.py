"""
bulk_export/models.py
──────────────────────────────────────────────────────────────
Statuts d'un export, transitions autorisées, configuration figée et identifiant d'export.

Aucun accès réseau ni base de données ici : uniquement des règles, testables seules.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


# ─── Statuts ──────────────────────────────────────────────────────────────────

class ExportStatus(str, Enum):
    PENDING = "PENDING"        # créé, pas encore démarré
    RUNNING = "RUNNING"        # récupération en cours
    STOPPING = "STOPPING"      # arrêt demandé, page en cours de finalisation
    PAUSED = "PAUSED"          # arrêté proprement, reprenable
    FAILED = "FAILED"          # erreur ; reprenable depuis le dernier point sûr
    INCOMPLETE = "INCOMPLETE"  # collecte arrêtée, complétude non démontrée
    VALIDATING = "VALIDATING"  # contrôles qualité en cours
    COMPLETED = "COMPLETED"    # complet ET validé (état final)


S = ExportStatus

# Pour chaque statut : les statuts vers lesquels on a le droit d'aller.
# COMPLETED n'est atteignable que depuis VALIDATING (règle n°5 de CLAUDE.md).
ALLOWED_TRANSITIONS: Mapping[ExportStatus, frozenset[ExportStatus]] = MappingProxyType({
    S.PENDING:    frozenset({S.RUNNING, S.FAILED}),
    # RUNNING → PAUSED : cas d'un redémarrage de l'application (bail expiré).
    S.RUNNING:    frozenset({S.STOPPING, S.PAUSED, S.FAILED, S.INCOMPLETE}),
    S.STOPPING:   frozenset({S.PAUSED, S.FAILED, S.INCOMPLETE}),
    S.PAUSED:     frozenset({S.RUNNING, S.FAILED}),
    # FAILED → VALIDATING : nouvelle validation après un échec de validation (si la pagination est
    # terminée : contrôlé dans state_store).
    S.FAILED:     frozenset({S.RUNNING, S.VALIDATING}),
    # INCOMPLETE → RUNNING n'est permis que si la pagination n'est pas terminée
    # (contrôle fait dans state_store, qui connaît pagination_finished).
    S.INCOMPLETE: frozenset({S.VALIDATING, S.RUNNING}),
    S.VALIDATING: frozenset({S.COMPLETED, S.INCOMPLETE, S.FAILED}),
    S.COMPLETED:  frozenset(),
})


class InvalidTransitionError(ValueError):
    """Changement de statut interdit (ex. PENDING → COMPLETED)."""


def check_transition(current: ExportStatus | str, new: ExportStatus | str) -> None:
    """Lève InvalidTransitionError si le passage ``current → new`` est interdit."""
    current, new = ExportStatus(current), ExportStatus(new)
    if new not in ALLOWED_TRANSITIONS[current]:
        raise InvalidTransitionError(
            f"Transition interdite : {current.value} → {new.value}. "
            f"Autorisées depuis {current.value} : "
            f"{', '.join(sorted(s.value for s in ALLOWED_TRANSITIONS[current])) or 'aucune'}."
        )


# ─── Identifiant d'export ─────────────────────────────────────────────────────

# Exemple : exp_20261015T143000Z_9f3a1c2b
EXPORT_ID_RE = re.compile(r"^exp_\d{8}T\d{6}Z_[0-9a-f]{8}$")


def new_export_id(now: datetime | None = None) -> str:
    """Identifiant d'opération : horodatage UTC + suffixe aléatoire.

    C'est l'identifiant de l'*opération d'export*, pas celui d'une mention
    (la règle n°6 de CLAUDE.md concerne les mentions)."""
    now = now or datetime.now(timezone.utc)
    return f"exp_{now.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}_{secrets.token_hex(4)}"


def validate_export_id(export_id: str) -> str:
    """Refuse tout identifiant hors format (ex. ``../../etc``)."""
    if not isinstance(export_id, str) or not EXPORT_ID_RE.fullmatch(export_id):
        raise ValueError("Identifiant d'export invalide.")
    return export_id


# ─── Configuration figée ──────────────────────────────────────────────────────

# Filtres documentés par l'API (audit_api.md §1). Les paramètres techniques
# (token, rows, random, nextCursorMark) ne sont PAS des filtres.
API_FILTER_KEYS = frozenset({
    "attribute", "attribute-negative", "attribute-positive", "brand", "category",
    "subcategory", "country", "market", "product", "rating", "source",
    "start-date", "end-date",
})

ALLOWED_BATCH_SIZES = (10_000, 25_000, 50_000)
DEFAULT_BATCH_SIZE = 25_000
ROWS_MAX = 1_000  # documenté par le fournisseur (audit_api.md, point 1)
# xlsx et plat : formats dérivés (Excel, et format « plat » de utils.postprocess_reviews).
ALLOWED_OUTPUT_FORMATS = frozenset({"csv", "jsonl", "zip", "xlsx", "plat"})

# Tout nom de champ contenant l'un de ces mots est refusé dans une configuration.
_SECRET_WORDS = ("token", "password", "passwd", "secret", "apikey", "api_key",
                 "service_key", "authorization", "database_url", "credential")


def _looks_like_secret_key(key: str) -> bool:
    k = str(key).lower().replace("-", "_")
    return any(word in k for word in _SECRET_WORDS)


def _reject_secret_keys(obj: Any, path: str = "") -> None:
    """Parcourt un objet JSON et refuse tout champ dont le nom ressemble à un secret."""
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            if _looks_like_secret_key(k):
                raise ValueError(f"Champ refusé dans la configuration : « {path}{k} » ressemble à un secret.")
            _reject_secret_keys(v, f"{path}{k}.")
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _reject_secret_keys(v, path)


class ConfigError(ValueError):
    """Configuration d'export invalide."""


@dataclass(frozen=True)
class ExportConfig:
    """Paramètres d'un export, figés au démarrage (toute modification = nouvel export).

    ``filters`` contient exactement les paramètres de filtre envoyés à l'API
    (sortie de ``utils.build_filter_params``), sous forme de texte.
    """
    name: str
    filters: Mapping[str, str]
    output_formats: tuple[str, ...] = ("csv", "jsonl", "zip", "xlsx", "plat")
    batch_size: int = DEFAULT_BATCH_SIZE
    rows: int = ROWS_MAX
    random: bool = False
    # Réglages des empreintes (decision_identifiant.md) : figés avec l'export
    # pour que les empreintes restent recalculables à l'identique.
    fingerprint: Mapping[str, Any] = field(default_factory=dict)
    # Règle de fin de pagination (api_adapter.DEFAULT_PAGINATION) : figée pour la traçabilité.
    pagination: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ConfigError("Le nom de la configuration est obligatoire.")
        if self.random:
            raise ConfigError("`random` est interdit pour un export exhaustif (règle n°11).")
        if self.batch_size not in ALLOWED_BATCH_SIZES:
            raise ConfigError(f"Taille de lot invalide : {self.batch_size}. Valeurs possibles : {ALLOWED_BATCH_SIZES}.")
        if not isinstance(self.rows, int) or not 1 <= self.rows <= ROWS_MAX:
            raise ConfigError(f"`rows` doit être compris entre 1 et {ROWS_MAX}.")

        formats = tuple(self.output_formats)
        unknown = set(formats) - ALLOWED_OUTPUT_FORMATS
        if not formats or unknown:
            raise ConfigError(f"Formats de sortie invalides : {sorted(unknown) or 'aucun'}.")

        clean: dict[str, str] = {}
        for key, value in dict(self.filters).items():
            if _looks_like_secret_key(key):
                raise ConfigError(f"Filtre refusé : « {key} » ressemble à un secret.")
            if key not in API_FILTER_KEYS:
                raise ConfigError(f"Filtre inconnu de l'API : « {key} ».")
            if not isinstance(value, str) or not value.strip():
                raise ConfigError(f"Le filtre « {key} » doit être un texte non vide.")
            clean[key] = value
        _reject_secret_keys(dict(self.fingerprint), "fingerprint.")
        _reject_secret_keys(dict(self.pagination), "pagination.")
        # Import tardif : vérifie les réglages sans créer de dépendance circulaire.
        from bulk_export.api_adapter import merged_pagination
        from bulk_export.fingerprints import merged_settings
        try:
            # Les valeurs par défaut sont ÉCRITES dans la configuration : un futur changement de
            # valeur par défaut ne modifiera jamais en silence un export déjà créé.
            fingerprint = merged_settings(self.fingerprint)
            pagination = merged_pagination(self.pagination)
        except ValueError as exc:
            raise ConfigError(str(exc)) from None

        # Rendre les dictionnaires non modifiables après création.
        object.__setattr__(self, "filters", MappingProxyType(dict(sorted(clean.items()))))
        object.__setattr__(self, "fingerprint", MappingProxyType(fingerprint))
        object.__setattr__(self, "pagination", MappingProxyType(pagination))
        object.__setattr__(self, "output_formats", tuple(sorted(set(formats))))

    # — Sérialisation —

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "filters": dict(self.filters),
            "output_formats": list(self.output_formats),
            "batch_size": self.batch_size,
            "rows": self.rows,
            "random": self.random,
            "fingerprint": dict(self.fingerprint),
            "pagination": dict(self.pagination),
        }

    def to_json(self) -> str:
        """JSON canonique : clés triées, sans espace superflu (sert au calcul de config_hash)."""
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    @property
    def config_hash(self) -> str:
        """Empreinte SHA-256 de la configuration : même configuration = même empreinte."""
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExportConfig":
        if not isinstance(data, Mapping):
            raise ConfigError("La configuration doit être un objet JSON.")
        _reject_secret_keys(data)
        known = {"name", "filters", "output_formats", "batch_size", "rows", "random", "fingerprint", "pagination"}
        unknown = set(data) - known
        if unknown:
            raise ConfigError(f"Champs inconnus dans la configuration : {sorted(unknown)}.")
        try:
            return cls(**dict(data))
        except TypeError as exc:
            raise ConfigError(f"Configuration incomplète : {exc}") from None

    @classmethod
    def from_json(cls, text: str) -> "ExportConfig":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"JSON illisible (ligne {exc.lineno}).") from None
        return cls.from_dict(data)
