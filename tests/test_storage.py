"""Client Supabase Storage contre un faux serveur (envoi par morceaux TUS, reprise, lecture, lien signé)."""

import base64
import json

import pytest
import requests

from bulk_export.storage import LocalStorage, StorageError, SupabaseStorage

FAKE_KEY = "sb_secret_FAKEkey1234567890"
FAKE_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.FAKEsignatureFAKEsig"


class Resp:
    def __init__(self, status, headers=None, body=b"", json_body=None):
        self.status_code, self.headers = status, headers or {}
        self.content = json.dumps(json_body).encode() if json_body is not None else body

    def json(self):
        return json.loads(self.content)

    def iter_content(self, n):
        for i in range(0, len(self.content), n):
            yield self.content[i:i + n]

    def close(self):
        pass


class FakeSupabase:
    """Sous-ensemble de l'API Storage : TUS (POST/PATCH/HEAD), GET authentifié, DELETE, sign."""

    def __init__(self, fail_patch_at=None):
        self.objects, self.uploads, self.calls = {}, {}, []
        self.fail_patch_at = set(fail_patch_at or [])
        self.patch_count = 0

    def request(self, method, url, timeout=None, headers=None, data=None, json=None, stream=False):
        self.calls.append((method, url, dict(headers or {})))
        path = url.split("/storage/v1", 1)[1]
        if method == "POST" and path == "/upload/resumable":
            meta = dict(item.split(" ") for item in headers["Upload-Metadata"].split(","))
            name = base64.b64decode(meta["objectName"]).decode()
            self.uploads["u1"] = {"name": name, "length": int(headers["Upload-Length"]), "data": b""}
            return Resp(201, {"Location": "https://fake.supabase.co/storage/v1/upload/resumable/u1"})
        if method == "PATCH":
            self.patch_count += 1
            up = self.uploads["u1"]
            if self.patch_count in self.fail_patch_at:
                up["data"] += data[: len(data) // 2]  # le serveur a reçu une partie, puis coupure
                raise requests.ConnectionError("coupure simulée token=" + FAKE_KEY)
            assert int(headers["Upload-Offset"]) == len(up["data"]), "reprise au mauvais endroit"
            up["data"] += data
            if len(up["data"]) == up["length"]:
                self.objects[up["name"]] = up["data"]
            return Resp(204, {"Upload-Offset": str(len(up["data"]))})
        if method == "HEAD":
            return Resp(200, {"Upload-Offset": str(len(self.uploads["u1"]["data"]))})
        if method == "GET" and path.startswith("/object/authenticated/bucket-test/"):
            name = path.split("/bucket-test/", 1)[1]
            return Resp(200, body=self.objects[name]) if name in self.objects else Resp(404, body=b"absent")
        if method == "DELETE":
            for p in json["prefixes"]:
                self.objects.pop(p, None)
            return Resp(200, json_body=[])
        if method == "POST" and path.startswith("/object/sign/"):
            return Resp(200, json_body={"signedURL": f"{path}?token=FAKEsignedtoken"})
        return Resp(400, body=b"inattendu")


def storage(fake, key=FAKE_KEY, chunk=10):
    return SupabaseStorage("https://fake.supabase.co", key, "bucket-test", session=fake, chunk_size=chunk,
                           sleep=lambda s: None)


def test_envoi_par_morceaux_puis_relecture(tmp_path):
    fake = FakeSupabase()
    src = tmp_path / "f.bin"
    src.write_bytes(b"0123456789" * 3 + b"fin")
    s = storage(fake)
    assert s.upload_file(src, "exp/batches/batch_0001.jsonl.gz", "application/gzip") == 33
    assert fake.patch_count == 4
    assert b"".join(s.iter_bytes("exp/batches/batch_0001.jsonl.gz")) == src.read_bytes()


def test_reprise_apres_coupure(tmp_path):
    fake = FakeSupabase(fail_patch_at={2})
    src = tmp_path / "f.bin"
    src.write_bytes(bytes(range(256)) * 2)
    s = storage(fake, chunk=100)
    s.upload_file(src, "exp/x.bin", "application/octet-stream")
    assert fake.objects["exp/x.bin"] == src.read_bytes()
    assert any(m == "HEAD" for m, *_ in fake.calls)


def test_coupures_repetees_abandon_sans_secret(tmp_path):
    fake = FakeSupabase(fail_patch_at=set(range(1, 50)))
    src = tmp_path / "f.bin"
    src.write_bytes(b"x" * 100)
    with pytest.raises(StorageError) as info:
        storage(fake, chunk=10).upload_file(src, "exp/x.bin", "application/octet-stream")
    assert FAKE_KEY not in str(info.value)


def test_entetes_selon_le_type_de_cle(tmp_path):
    src = tmp_path / "f.bin"
    src.write_bytes(b"abc")
    fake = FakeSupabase()
    storage(fake).upload_file(src, "a", "text/plain")
    assert all(h["apikey"] == FAKE_KEY and "Authorization" not in h for _, _, h in fake.calls)
    fake = FakeSupabase()
    storage(fake, key=FAKE_JWT).upload_file(src, "a", "text/plain")
    assert all(h["Authorization"] == f"Bearer {FAKE_JWT}" for _, _, h in fake.calls)


def test_lien_signe_et_suppression(tmp_path):
    fake = FakeSupabase()
    s = storage(fake)
    url = s.signed_url("exp/output/export complete.csv", 3600, download_name="export complete.csv")
    assert url.startswith("https://fake.supabase.co/storage/v1/object/sign/bucket-test/exp/output/export%20complete.csv")
    assert "download=export%20complete.csv" in url
    fake.objects["exp/a"] = b"1"
    s.delete(["exp/a"])
    assert "exp/a" not in fake.objects


def test_lecture_fichier_absent():
    with pytest.raises(StorageError, match="404"):
        list(storage(FakeSupabase()).iter_bytes("rien"))


def test_configuration_manquante():
    with pytest.raises(StorageError, match="non configuré"):
        SupabaseStorage("", "", "b")
    with pytest.raises(StorageError, match="https"):
        SupabaseStorage("http://exemple.test", FAKE_KEY, "b")


def test_stockage_local_refuse_les_chemins_hors_dossier(tmp_path):
    s = LocalStorage(tmp_path / "store")
    with pytest.raises(StorageError):
        s.upload_file(__file__, "../evasion.txt", "text/plain")
