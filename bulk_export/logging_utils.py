"""
bulk_export/logging_utils.py
──────────────────────────────────────────────────────────────
Masquage des secrets dans tout texte destiné aux journaux, à l'écran ou à la base (règle n°8).

Deux protections complémentaires :
1. les valeurs des secrets connus (enregistrées via ``register_secret``) sont remplacées partout ;
2. des motifs reconnaissables sont masqués même si la valeur n'a pas été enregistrée :
   ``token=…`` dans une adresse, ``Bearer …``, mot de passe dans ``postgresql://user:motdepasse@…``,
   jetons JWT (clés Supabase).
"""

from __future__ import annotations

import logging
import re
import threading

MASK = "***"

_known_secrets: set[str] = set()
_lock = threading.Lock()

_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    # token=VALEUR ou token%3DVALEUR dans une adresse ou un texte (jusqu'au prochain séparateur)
    (re.compile(r"(?i)(\btoken(?:=|%3D))[^&\s'\"<>]+"), r"\1" + MASK),
    # "token": "VALEUR" ou token: VALEUR
    (re.compile(r"""(?i)(["']?\btoken["']?\s*[:=]\s*["']?)[^"'\s,}&]+"""), r"\1" + MASK),
    # En-tête d'autorisation
    (re.compile(r"(?i)(\bbearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1" + MASK),
    # Mot de passe dans une URL de connexion : scheme://user:MOTDEPASSE@hote
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^:/\s@]+:)[^@\s]+@"), r"\1" + MASK + "@"),
    # Jeton JWT (ex. clé service_role Supabase)
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), MASK),
)


def register_secret(value: str | None) -> None:
    """Ajoute une valeur secrète à masquer partout. Les valeurs trop courtes sont ignorées
    (masquer « a » rendrait tout illisible sans rien protéger)."""
    if value and len(value) >= 6:
        with _lock:
            _known_secrets.add(value)


def mask(text: object) -> str:
    """Renvoie le texte avec tous les secrets connus ou reconnaissables remplacés par ***."""
    out = str(text)
    with _lock:
        known = sorted(_known_secrets, key=len, reverse=True)
    for secret in known:
        out = out.replace(secret, MASK)
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    return out


class SecretMaskingFilter(logging.Filter):
    """Filtre ``logging`` : masque le message final de chaque enregistrement."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # message mal formé : on garde le gabarit brut
            message = str(record.msg)
        record.msg = mask(message)
        record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = mask(logging.Formatter().formatException(record.exc_info))
        elif record.exc_text:
            record.exc_text = mask(record.exc_text)
        return True


def get_logger(name: str = "bulk_export") -> logging.Logger:
    """Logger du paquet, toujours équipé du filtre de masquage."""
    logger = logging.getLogger(name)
    if not any(isinstance(f, SecretMaskingFilter) for f in logger.filters):
        logger.addFilter(SecretMaskingFilter())
    return logger
