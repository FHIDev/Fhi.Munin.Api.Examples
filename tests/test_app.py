"""Nettsiden trykket gjennom med Streamlits AppTest, uten nettverk: alle HTTP-kall får ferdige svar."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from unittest.mock import patch

import pytest
import requests
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def svar(status: int, kropp) -> requests.Response:
    r = requests.Response()
    r.status_code = status
    r._content = json.dumps(kropp).encode()
    return r


TOKEN = "h." + base64.urlsafe_b64encode(json.dumps({"roles": ["ingest.provider.fhitest"]}).encode()).decode().rstrip("=") + ".s"

SVAR = {
    ("GET", "/api/ingest/v1/health"): svar(200, {"status": "healthy", "version": {"major": 1, "minor": 17},
                                                 "authentication": {"schemes": [{"scheme": "EntraId", "status": "healthy"}]}}),
    ("GET", "/api/ingest/v1/kilder"): svar(200, [{"code": "test", "preferredTerm": "Test", "dataleverandorNavn": "fhitest"}]),
    ("PATCH", "/api/ingest/v1/kilder/test/variabler/EKSEMPEL_VARIABEL"): svar(
        201, {"variabel": {"id": "1", "code": "EKSEMPEL_VARIABEL", "activeVersjon": {"preferredTerm": "Eksempelvariabel"}}}),
    ("GET", "/api/export/v1/metadata/variables"): svar(200, {"items": [{"code": "EKSEMPEL_VARIABEL", "name": "Eksempelvariabel"}],
                                                             "pageToken": None}),
    ("GET", "/api/export/v2/healthdcat-ap/catalog"): svar(200, {"dct:title": {"@value": "Katalog"},
                                                                "dcat:datasetSeries": [{"dct:identifier": "test"}], "dcat:dataset": []}),
    ("GET", "/api/export/v1/datasets"): svar(200, {"items": [{"kilde": {"code": "test", "preferredTerm": "Test"}}], "pageToken": None}),
    ("GET", "/api/export/v1/datasets/test"): svar(200, {"kilde": {"code": "test", "datasamlinger": [{"code": "D1", "variabler": ["V1"]}]},
                                                        "variabler": [{"code": "V1", "kodeverklinker": [{"kodeverkType": "ICD-10", "kodeverkReference": "x"}]}]}),
}


def falsk_request(self, metode, adresse, **_):
    sti = "/" + adresse.split("/", 3)[3].split("?")[0]
    return SVAR[(metode, sti)]


@pytest.fixture
def side(monkeypatch):
    for navn, verdi in {"MUNIN_TENANT_ID": "t", "MUNIN_CLIENT_ID": "c", "MUNIN_CLIENT_SECRET": "s",
                        "MUNIN_SCOPE": "api://app/.default"}.items():
        monkeypatch.setenv(navn, verdi)
    with patch.object(requests.Session, "request", falsk_request), \
         patch.object(requests.Session, "post", lambda self, *a, **k: svar(200, {"access_token": TOKEN, "expires_in": 3600})):
        yield AppTest.from_file(APP, default_timeout=30).run()


def trykk(at: AppTest, tekst: str) -> AppTest:
    next(b for b in at.button if b.label == tekst).click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


@pytest.mark.parametrize("knapp, forventet", [
    ("Helsesjekk", "Status: healthy"),
    ("Lagre variabel", "opprettet (201)"),
    ("HealthDCAT-katalogen", "1 kilder (serier)"),
])
def test_knappene_viser_resultatet(side, knapp, forventet):
    at = trykk(side, knapp)
    assert any(forventet in s.value for s in at.success), [s.value for s in at.success]


@pytest.mark.parametrize("knapp", ["Mine kilder", "Les tilbake (Eksport)", "Alle kilder", "Vis datasett"])
def test_tabellknappene_viser_en_tabell(side, knapp):
    at = trykk(side, knapp)
    assert at.dataframe, f"{knapp} viste ingen tabell"
    assert not at.error, [e.value for e in at.error]


def test_403_gir_norsk_forklaring(side):
    SVAR_403 = svar(403, {"error": "Token does not grant access to kilde 'test'", "correlationId": "k1"})
    with patch.dict(SVAR, {("GET", "/api/ingest/v1/kilder"): SVAR_403}):
        at = trykk(side, "Mine kilder")
    assert any("Ingen tilgang (403)" in e.value for e in at.error)
