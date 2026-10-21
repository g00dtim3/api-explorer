"""
bulk_export/storage.py
──────────────────────────────────────────────────────────────
Fichiers finaux dans Supabase Storage (bucket PRIVÉ), via l'API HTTP de Supabase (pas de bibliothèque en plus).

- envoi par morceaux de 6 Mo, reprenable (protocole TUS, celui de Supabase pour les gros fichiers) :
  si un morceau échoue, on demande au serveur où il en est, puis on reprend à cet endroit ;
- lecture en flux (jamais le fichier entier en mémoire) ;
- lien signé temporaire pour le téléchargement : le fichier ne transite pas par Streamlit ;
- les messages d'erreur sont masqués (clé et jetons de liens signés).

``LocalStorage`` : même interface sur un dossier local (tests, essais sans Supabase).
"""

from __future__ import annotations

import base64
import os
import shutil
import time
import urllib.parse
from pathlib import Path
from typing import Iterator, Protocol, Sequence

import requests

from bulk_export.logging_utils import get_logger, mask, register_secret

logger = get_logger(__name__)

TUS_CHUNK = 6 * 1024 * 1024  # taille imposée par Supabase pour l'envoi reprenable
READ_CHUNK = 1024 * 1024


class StorageError(RuntimeError):
    """Erreur de stockage (message masqué)."""

    def __init__(self, message: str):
        super().__init__(mask(message))


class Storage(Protocol):
    def upload_file(self, local_path: str | Path, remote_path: str, content_type: str) -> int: ...
    def iter_bytes(self, remote_path: str) -> Iterator[bytes]: ...
    def delete(self, remote_paths: Sequence[str]) -> None: ...
    def signed_url(self, remote_path: str, expires_s: int = 3600, download_name: str | None = None) -> str: ...


def _quote_path(path: str) -> str:
    return "/".join(urllib.parse.quote(part, safe="") for part in path.split("/"))


class SupabaseStorage:
    def __init__(self, supabase_url: str, key: str, bucket: str, *, session: requests.Session | None = None,
                 timeout: tuple[float, float] = (10.0, 300.0), chunk_size: int = TUS_CHUNK,
                 max_attempts: int = 5, sleep=time.sleep):
        if not supabase_url or not key:
            raise StorageError("Stockage non configuré : supabase_url et supabase_service_key sont nécessaires.")
        if not supabase_url.startswith(("https://", "http://127.0.0.1:", "http://localhost:")):
            raise StorageError("supabase_url doit commencer par https://")
        register_secret(key)
        self._base = supabase_url.rstrip("/") + "/storage/v1"
        self._key = key
        self.bucket = bucket
        self._session = session or requests.Session()
        self._timeout = timeout
        self._chunk = chunk_size
        self._max_attempts = max_attempts
        self._sleep = sleep

    def __repr__(self) -> str:
        return f"SupabaseStorage(bucket={self.bucket!r})"

    def _headers(self, extra: dict | None = None) -> dict:
        headers = {"apikey": self._key}
        # Ancienne clé service_role (JWT) : aussi dans Authorization. Nouvelle clé sb_secret_… : apikey seul.
        if self._key.startswith("eyJ"):
            headers["Authorization"] = f"Bearer {self._key}"
        headers.update(extra or {})
        return headers

    def _request(self, method: str, url: str, **kw) -> requests.Response:
        try:
            return self._session.request(method, url, timeout=self._timeout, **kw)
        except requests.RequestException as exc:
            raise StorageError(f"Stockage injoignable ({type(exc).__name__}).") from None

    @staticmethod
    def _check(resp: requests.Response, what: str, ok=(200, 201, 204)) -> None:
        if resp.status_code not in ok:
            body = (resp.content or b"")[:300].decode("utf-8", errors="replace")
            hint = ""
            if "Invalid Compact JWS" in body:
                # Constaté le 15/10/2026 : Storage refuse les nouvelles clés « sb_secret_… ».
                hint = (" → Storage n'accepte pas cette clé. Utilisez la clé « service_role » de l'onglet "
                        "« Legacy API Keys » (elle commence par eyJ…) dans supabase_service_key.")
            elif "required property 'authorization'" in body:
                # Constaté le 21/10/2026 (réhydratation) : clé qui ne commence pas par eyJ → pas d'en-tête Authorization.
                hint = (" → La clé utilisée ne commence pas par eyJ : elle n'est pas envoyée comme jeton. Mettez la "
                        "clé « service_role » de l'onglet « Legacy API Keys » (elle commence par eyJ…) dans "
                        "supabase_service_key (ou BULK_EXPORT_SUPABASE_SERVICE_KEY en ligne de commande).")
            raise StorageError(f"{what} : HTTP {resp.status_code} — {body}{hint}")

    # ─── Envoi reprenable (TUS) ──────────────────────────────────────────────

    def upload_file(self, local_path, remote_path: str, content_type: str) -> int:
        size = os.path.getsize(local_path)

        def b64(text: str) -> str:
            return base64.b64encode(text.encode("utf-8")).decode("ascii")

        meta = ",".join([f"bucketName {b64(self.bucket)}", f"objectName {b64(remote_path)}",
                         f"contentType {b64(content_type)}", f"cacheControl {b64('3600')}"])
        create = self._request("POST", f"{self._base}/upload/resumable", headers=self._headers({
            "Tus-Resumable": "1.0.0", "Upload-Length": str(size), "Upload-Metadata": meta, "x-upsert": "true"}))
        self._check(create, f"Création de l'envoi de {remote_path}", ok=(201,))
        location = create.headers.get("Location")
        if not location:
            raise StorageError(f"Envoi de {remote_path} : adresse d'envoi absente.")
        if location.startswith("/"):
            location = urllib.parse.urljoin(self._base, location)

        offset, failures = 0, 0
        with open(local_path, "rb") as fh:
            while offset < size or size == 0:
                fh.seek(offset)
                chunk = fh.read(self._chunk)
                try:
                    resp = self._request("PATCH", location, data=chunk, headers=self._headers({
                        "Tus-Resumable": "1.0.0", "Upload-Offset": str(offset),
                        "Content-Type": "application/offset+octet-stream"}))
                    self._check(resp, f"Envoi de {remote_path}", ok=(204,))
                    offset = int(resp.headers.get("Upload-Offset", offset + len(chunk)))
                    failures = 0
                except StorageError as exc:
                    failures += 1
                    if failures >= self._max_attempts:
                        raise
                    logger.warning("Envoi de %s interrompu à %d octets (%s) : reprise.", remote_path, offset, exc)
                    self._sleep(min(2 ** failures, 30))
                    offset = self._server_offset(location, offset)
                if size == 0:
                    break
        if offset != size:
            raise StorageError(f"Envoi de {remote_path} incomplet : {offset} / {size} octets.")
        return size

    def _server_offset(self, location: str, fallback: int) -> int:
        """Où en est le serveur ? (reprise d'un envoi coupé)"""
        try:
            resp = self._request("HEAD", location, headers=self._headers({"Tus-Resumable": "1.0.0"}))
            if resp.status_code in (200, 204) and "Upload-Offset" in resp.headers:
                return int(resp.headers["Upload-Offset"])
        except StorageError:
            pass
        return fallback

    # ─── Lecture, suppression, lien signé ────────────────────────────────────

    def iter_bytes(self, remote_path: str) -> Iterator[bytes]:
        url = f"{self._base}/object/authenticated/{self.bucket}/{_quote_path(remote_path)}"
        resp = self._request("GET", url, headers=self._headers(), stream=True)
        self._check(resp, f"Lecture de {remote_path}", ok=(200,))
        try:
            for block in resp.iter_content(READ_CHUNK):
                if block:
                    yield block
        except requests.RequestException as exc:
            raise StorageError(f"Lecture de {remote_path} interrompue ({type(exc).__name__}).") from None
        finally:
            resp.close()

    def delete(self, remote_paths: Sequence[str]) -> None:
        paths = list(remote_paths)
        for i in range(0, len(paths), 100):
            resp = self._request("DELETE", f"{self._base}/object/{self.bucket}", headers=self._headers(),
                                 json={"prefixes": paths[i:i + 100]})
            self._check(resp, "Suppression de fichiers", ok=(200, 204))

    def signed_url(self, remote_path: str, expires_s: int = 3600, download_name: str | None = None) -> str:
        url = f"{self._base}/object/sign/{self.bucket}/{_quote_path(remote_path)}"
        resp = self._request("POST", url, headers=self._headers(), json={"expiresIn": int(expires_s)})
        self._check(resp, f"Lien signé pour {remote_path}", ok=(200,))
        signed = resp.json().get("signedURL") or resp.json().get("signedUrl")
        if not signed:
            raise StorageError(f"Lien signé pour {remote_path} : réponse inattendue.")
        full = signed if signed.startswith("http") else f"{self._base}{signed}"
        if download_name:
            sep = "&" if "?" in full else "?"
            full += f"{sep}download={urllib.parse.quote(download_name)}"
        return full


class LocalStorage:
    """Stockage dans un dossier local, même interface (tests et essais hors Supabase)."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.bucket = "local"

    def _path(self, remote_path: str) -> Path:
        p = (self.root / remote_path).resolve()
        if self.root.resolve() not in p.parents:
            raise StorageError("Chemin de fichier invalide.")
        return p

    def upload_file(self, local_path, remote_path: str, content_type: str) -> int:
        dest = self._path(remote_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local_path, dest)
        return dest.stat().st_size

    def iter_bytes(self, remote_path: str) -> Iterator[bytes]:
        path = self._path(remote_path)
        if not path.exists():
            raise StorageError(f"Lecture de {remote_path} : fichier absent.")
        with open(path, "rb") as fh:
            while block := fh.read(READ_CHUNK):
                yield block

    def delete(self, remote_paths: Sequence[str]) -> None:
        for p in remote_paths:
            self._path(p).unlink(missing_ok=True)

    def signed_url(self, remote_path: str, expires_s: int = 3600, download_name: str | None = None) -> str:
        return self._path(remote_path).as_uri()


def build_storage(settings) -> SupabaseStorage:
    """Stockage Supabase à partir des paramètres (section [bulk_export] des secrets)."""
    return SupabaseStorage(settings.supabase_url or "", settings.supabase_service_key or "", settings.storage_bucket)
