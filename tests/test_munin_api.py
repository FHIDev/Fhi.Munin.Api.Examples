"""Tester for munin_api uten nettverk: hvert HTTP-kall erstattes av et ferdig svar."""

from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock

import pytest
import requests

from munin_api import (EksportKlient, IngestKlient, Innstillinger, MuninFeil, TokenKilde, feil_fra_svar,
                       katalog_oversikt)


def svar(status: int, kropp=None, hoder=None) -> requests.Response:
    r = requests.Response()
    r.status_code = status
    r.headers.update(hoder or {})
    r._content = json.dumps(kropp).encode() if kropp is not None else b""
    return r


def token_med_roller(*roller: str) -> str:
    nyttelast = base64.urlsafe_b64encode(json.dumps({"roles": list(roller)}).encode()).decode().rstrip("=")
    return f"hode.{nyttelast}.signatur"


@pytest.fixture
def innstillinger() -> Innstillinger:
    return Innstillinger("tenant", "klient", "hemmelig", "api://app/.default", "https://ingest.test", "https://eksport.test")


@pytest.fixture
def okt() -> MagicMock:
    okt = MagicMock(spec=requests.Session)
    okt.post.return_value = svar(200, {"access_token": token_med_roller("ingest.provider.fhitest"), "expires_in": 3600})
    return okt


def test_tokenet_hentes_en_gang_og_gjenbrukes(innstillinger, okt):
    tokens = TokenKilde(innstillinger, okt)
    assert tokens.token() == tokens.token()
    assert okt.post.call_count == 1
    sendt = okt.post.call_args.kwargs["data"]
    assert sendt["grant_type"] == "client_credentials" and sendt["scope"] == "api://app/.default"


def test_rollene_leses_fra_tokenet(innstillinger, okt):
    assert TokenKilde(innstillinger, okt).roller() == ["ingest.provider.fhitest"]


def test_feil_hemmelighet_gir_entras_forklaring(innstillinger, okt):
    okt.post.return_value = svar(401, {"error": "invalid_client", "error_description": "AADSTS7000215: Invalid client secret."})
    with pytest.raises(MuninFeil, match="AADSTS7000215"):
        TokenKilde(innstillinger, okt).token()


def test_manglende_innstillinger_navngis(monkeypatch):
    for navn in ("MUNIN_TENANT_ID", "MUNIN_CLIENT_ID", "MUNIN_CLIENT_SECRET", "MUNIN_SCOPE"):
        monkeypatch.delenv(navn, raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None, raising=False)
    with pytest.raises(MuninFeil, match="MUNIN_CLIENT_SECRET"):
        Innstillinger.fra_miljo()


def test_lagre_variabel_sender_patch_med_token_og_bare_feltene_som_er_gitt(innstillinger, okt):
    okt.request.return_value = svar(201, {"variabel": {"id": "1", "code": "V1"}})
    ingest = IngestKlient("https://ingest.test", TokenKilde(innstillinger, okt))

    status, _ = ingest.lagre_variabel("test", "V1", "Navn")

    assert status == 201
    metode, adresse = okt.request.call_args.args
    assert (metode, adresse) == ("PATCH", "https://ingest.test/api/ingest/v1/kilder/test/variabler/V1")
    assert okt.request.call_args.kwargs["json"] == {"preferredTerm": "Navn"}
    assert okt.request.call_args.kwargs["headers"]["Authorization"].startswith("Bearer ")


def test_koder_kan_ikke_bryte_ut_av_stien(innstillinger, okt):
    okt.request.return_value = svar(200, {"variabel": {}})
    IngestKlient("https://ingest.test", TokenKilde(innstillinger, okt)).lagre_variabel("te/st", "V?1", "Navn")
    assert okt.request.call_args.args[1] == "https://ingest.test/api/ingest/v1/kilder/te%2Fst/variabler/V%3F1"


def test_helsesjekken_sender_ikke_token(okt):
    okt.request.return_value = svar(200, {"status": "healthy"})
    IngestKlient("https://ingest.test", None, okt).helse()
    assert "Authorization" not in okt.request.call_args.kwargs["headers"]


@pytest.mark.parametrize("status, ord", [(401, "MUNIN_SCOPE"), (403, "rollen"), (409, "Konflikt"), (413, "30 MB"),
                                        (404, "finnes ikke"), (503, "Feil hos Munin")])
def test_hver_statuskode_far_en_norsk_forklaring(status, ord):
    feil = feil_fra_svar(svar(status, {"error": "detalj fra API-et", "correlationId": "abc"}))
    assert ord in feil.melding and "detalj fra API-et" in feil.melding
    assert feil.status == status and feil.korrelasjons_id == "abc"


def test_valideringsfeil_tar_med_feltene():
    feil = feil_fra_svar(svar(400, {"error": "Validering feilet", "details": {"PreferredTerm": ["påkrevd"]}}))
    assert feil.detaljer == {"PreferredTerm": ["påkrevd"]}
    assert "PreferredTerm: påkrevd" in str(feil)


def test_problemdetails_fra_eksport_leses_ogsa():
    feil = feil_fra_svar(svar(403, {"title": "Forbidden", "detail": "Missing scope export.datasets.read"}))
    assert "export.datasets.read" in feil.melding


def test_429_sier_hvor_lenge_du_skal_vente():
    assert "30 sekunder" in feil_fra_svar(svar(429, {}, {"Retry-After": "30"})).melding


def test_variabel_leses_fra_alle_sider_i_eksport(innstillinger, okt):
    okt.request.side_effect = [
        svar(200, {"items": [{"code": "A"}], "pageToken": "neste"}),
        svar(200, {"items": [{"code": "v1", "name": "Navn"}], "pageToken": None}),
    ]
    rader = EksportKlient("https://eksport.test", TokenKilde(innstillinger, okt)).variabel("test", "V1")
    assert rader == [{"code": "v1", "name": "Navn"}]
    assert okt.request.call_args_list[1].kwargs["params"] == {"kildeCode": "test", "pageToken": "neste"}


def test_nettverksfeil_blir_en_muninfeil(okt):
    okt.request.side_effect = requests.ConnectionError("ingen forbindelse")
    with pytest.raises(MuninFeil, match="Fikk ikke kontakt"):
        IngestKlient("https://ingest.test", None, okt).helse()


def test_katalogoversikten_leser_serier_og_datasett():
    katalog = {
        "dct:title": [{"@language": "en", "@value": "Catalogue"}, {"@language": "nb", "@value": "Katalog"}],
        "dcat:datasetSeries": [{"dct:identifier": "NPR", "dct:title": {"@language": "nb", "@value": "Norsk pasientregister"}}],
        "dcat:dataset": [{}, {}],
    }
    assert katalog_oversikt(katalog) == {"tittel": "Katalog", "antall_datasett": 2,
                                         "serier": [{"kode": "NPR", "tittel": "Norsk pasientregister"}]}


def test_feltfeil_som_ikke_er_en_ordbok_gir_likevel_en_lesbar_feil():
    feil = feil_fra_svar(svar(400, {"error": "Validering feilet", "details": ["noe er galt"]}))
    assert "noe er galt" in str(feil)


def test_et_svar_som_ikke_er_json_blir_en_muninfeil(okt):
    html = requests.Response()
    html.status_code = 200
    html.headers["Content-Type"] = "text/html"
    html._content = b"<html>innlogging</html>"
    okt.request.return_value = html
    with pytest.raises(MuninFeil, match="ikke med JSON"):
        IngestKlient("https://ingest.test", None, okt).helse()


def test_samme_sidetoken_to_ganger_stopper_i_stedet_for_a_ga_i_ring(innstillinger, okt):
    okt.request.side_effect = [svar(200, {"items": [], "pageToken": "x"}), svar(200, {"items": [], "pageToken": "x"})]
    with pytest.raises(MuninFeil, match="samme sidetoken"):
        EksportKlient("https://eksport.test", TokenKilde(innstillinger, okt)).variabel("test", "V1")


def test_tokensvar_uten_token_forklares(innstillinger, okt):
    okt.post.return_value = svar(200, {"token_type": "Bearer"})
    with pytest.raises(MuninFeil, match="uten noe token"):
        TokenKilde(innstillinger, okt).token()


def test_kildelisten_og_datasettet_ber_om_riktige_parametre(innstillinger, okt):
    eksport = EksportKlient("https://eksport.test", TokenKilde(innstillinger, okt))
    okt.request.return_value = svar(200, {"items": [{"kilde": {"code": "test"}}], "pageToken": None})
    assert eksport.kildeliste() == [{"code": "test"}]
    assert okt.request.call_args.kwargs["params"] == {"include": "kilde", "pageSize": 100}

    okt.request.return_value = svar(200, {"kilde": {"code": "test"}, "variabler": []})
    eksport.datasett("test")
    assert okt.request.call_args.args[1] == "https://eksport.test/api/export/v1/datasets/test"
    assert okt.request.call_args.kwargs["params"] == {"nestedVariables": "codes"}
