"""Innlogging med sertifikat: nøkkelparet fra lag_sertifikat.py og den signerte påstanden til Entra."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
from unittest.mock import MagicMock

import pytest
import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

import lag_sertifikat
from munin_api import Innstillinger, MuninFeil, TokenKilde, klientpastand

TOKEN_ADRESSE = "https://login.microsoftonline.com/tenant/oauth2/v2.0/token"


def b64(del_: str) -> bytes:
    return base64.urlsafe_b64decode(del_ + "=" * (-len(del_) % 4))


@pytest.fixture
def par(tmp_path):
    nokkel, sertifikat = tmp_path / "nokler" / "munin-klient.key", tmp_path / "munin-klient.cer"
    lag_sertifikat.lag("test-klient", 30, nokkel, sertifikat)
    return nokkel, sertifikat


@pytest.fixture
def innstillinger(par) -> Innstillinger:
    nokkel, sertifikat = par
    return Innstillinger("tenant", "klient-id", None, "api://app/.default",
                         cert_nokkel_sti=str(nokkel), cert_sti=str(sertifikat))


@pytest.mark.skipif(os.name == "nt", reason="Unix-rettigheter")
def test_den_private_nokkelen_kan_bare_eieren_lese(par):
    nokkel, _ = par
    assert stat.S_IMODE(nokkel.stat().st_mode) == 0o600
    assert stat.S_IMODE(nokkel.parent.stat().st_mode) == 0o700


def test_sertifikatfilen_holder_ingen_privat_nokkel(par):
    _, sertifikat = par
    innhold = sertifikat.read_text()
    assert "BEGIN CERTIFICATE" in innhold and "PRIVATE KEY" not in innhold


def test_en_nokkel_som_finnes_skrives_ikke_over(par):
    nokkel, sertifikat = par
    with pytest.raises(FileExistsError):
        lag_sertifikat.lag("x", 30, nokkel, sertifikat)


def test_pastanden_er_signert_og_peker_pa_sertifikatet(innstillinger, par):
    _, sertifikatfil = par
    hode_b64, innhold_b64, signatur_b64 = klientpastand(innstillinger, TOKEN_ADRESSE).split(".")
    hode, innhold = json.loads(b64(hode_b64)), json.loads(b64(innhold_b64))

    sertifikat = x509.load_pem_x509_certificate(sertifikatfil.read_bytes())
    der = sertifikat.public_bytes(serialization.Encoding.DER)
    assert hode["alg"] == "RS256"
    assert b64(hode["x5t#S256"]) == hashlib.sha256(der).digest()
    assert innhold["aud"] == TOKEN_ADRESSE
    assert innhold["iss"] == innhold["sub"] == "klient-id"
    assert innhold["exp"] - innhold["nbf"] == 600

    # Kaster InvalidSignature hvis signaturen ikke stemmer med sertifikatets offentlige nøkkel.
    sertifikat.public_key().verify(b64(signatur_b64), f"{hode_b64}.{innhold_b64}".encode(),
                                   padding.PKCS1v15(), hashes.SHA256())


def test_tokenforesporselen_sender_pastanden_og_ingen_hemmelighet(innstillinger):
    okt = MagicMock(spec=requests.Session)
    resp = requests.Response()
    resp.status_code = 200
    resp._content = json.dumps({"access_token": "a.b.c", "expires_in": 3600}).encode()
    okt.post.return_value = resp

    TokenKilde(innstillinger, okt).token()

    data = okt.post.call_args.kwargs["data"]
    assert "client_secret" not in data
    assert data["client_assertion_type"] == "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
    assert data["client_assertion"].count(".") == 2


def test_en_nokkelsti_som_ikke_finnes_forklares(innstillinger):
    innstillinger.cert_nokkel_sti = "/finnes/ikke.key"
    with pytest.raises(MuninFeil, match="MUNIN_CERT_KEY_PATH"):
        klientpastand(innstillinger, TOKEN_ADRESSE)


def test_sertifikat_er_nok_uten_hemmelighet_i_miljoet(monkeypatch, par):
    nokkel, sertifikat = par
    for navn, verdi in {"MUNIN_TENANT_ID": "t", "MUNIN_CLIENT_ID": "c", "MUNIN_SCOPE": "s",
                        "MUNIN_CERT_KEY_PATH": str(nokkel), "MUNIN_CERT_PATH": str(sertifikat)}.items():
        monkeypatch.setenv(navn, verdi)
    monkeypatch.delenv("MUNIN_CLIENT_SECRET", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None, raising=False)
    innst = Innstillinger.fra_miljo()
    assert innst.client_secret is None and innst.cert_sti == str(sertifikat)
