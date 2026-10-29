"""En liten klient for Munins Ingest-API og Eksport-API.

Modulen gjør tre ting:

1. henter et tilgangstoken fra Microsoft Entra ID med «client credentials»
   (klient-id og et sertifikat eller en klienthemmelighet, ingen innlogget person);
2. kaller Ingest-API-et (skrive metadata) og Eksport-API-et (lese metadata);
3. gjør feilsvar om til én feiltype, MuninFeil, med en norsk forklaring.

Alt som er hemmelig eller miljøspesifikt leses fra miljøvariabler (se
.env.example). Ingenting av det står i koden.
"""

from __future__ import annotations

import base64
import json
import hashlib
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote

import requests

# Hvor lenge vi venter på et svar før vi gir opp, i sekunder. HealthDCAT-katalogen
# er stor, så den får lengre tid (se ExportKlient.healthdcat_katalog).
STANDARD_TIDSAVBRUDD = 30
KATALOG_TIDSAVBRUDD = 180

# Øvre grense for antall sider vi blar gjennom, så en feil i API-et aldri gir en evig løkke.
MAKS_SIDER = 1000


class MuninFeil(Exception):
    """Et kall til Munin eller til Entra ID gikk galt.

    `melding` er en norsk forklaring som kan vises til brukeren. `status` er
    HTTP-statuskoden (None når vi aldri fikk et svar), `korrelasjons_id` er
    id-en FHI trenger for å finne kallet i loggene, og `detaljer` holder
    feltfeil fra en valideringsfeil.
    """

    def __init__(
        self,
        melding: str,
        status: int | None = None,
        korrelasjons_id: str | None = None,
        detaljer: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(melding)
        self.melding = melding
        self.status = status
        self.korrelasjons_id = korrelasjons_id
        # Feltfeil skal være {felt: [meldinger]}; noe annet tas vare på som én melding.
        if detaljer and not isinstance(detaljer, dict):
            detaljer = {"feil": detaljer}
        self.detaljer = detaljer or {}

    def __str__(self) -> str:
        tekst = self.melding
        if self.detaljer:
            felt = "; ".join(f"{navn}: {', '.join(map(str, feil)) if isinstance(feil, list) else feil}"
                             for navn, feil in self.detaljer.items())
            tekst += f"\nFeltfeil: {felt}"
        if self.korrelasjons_id:
            tekst += f"\nKorrelasjons-id (oppgi den til FHI): {self.korrelasjons_id}"
        return tekst


# Forklaringene vi gir for de vanligste statuskodene. API-ets egen tekst legges
# til etterpå, siden den ofte sier nøyaktig hva som var galt.
FORKLARINGER = {
    400: "Ugyldig forespørsel (400): noe i det du sendte, var ikke gyldig. Se feltfeilene under.",
    401: ("Ikke autentisert (401): tokenet mangler, er utløpt eller er utstedt for feil API. "
          "Sjekk MUNIN_TENANT_ID, MUNIN_CLIENT_ID og MUNIN_SCOPE i .env."),
    403: ("Ingen tilgang (403): tokenet er gyldig, men klienten mangler rollen som trengs. "
          "Ingest krever ingest.provider.<dataleverandør> for kilden; eksport krever "
          "export.metadata.read eller export.datasets.read. Se «Roller i tokenet» og be FHI om tilgang."),
    404: ("Ikke funnet (404): kilden eller ressursen finnes ikke, eller API-et er ikke slått på "
          "i dette miljøet. Sjekk kildekoden og adressen."),
    409: ("Konflikt (409): en annen endring kom i veien, eller du prøver å endre noe som en annen "
          "kilde også bruker. Hent dataene på nytt og prøv igjen; ved delte entiteter, kontakt FHI."),
    412: "Utdatert versjon (412): ressursen er endret siden du hentet den. Hent den på nytt og prøv igjen.",
    413: ("For stor forespørsel (413): innholdet er over grensen API-et godtar (om lag 30 MB). "
          "Del opp innsendingen i mindre biter."),
    422: "Ugyldige egendefinerte egenskaper (422): se feltfeilene under.",
    429: "For mange forespørsler (429): vent litt og prøv igjen.",
}


def _forklaring(status: int) -> str:
    if status in FORKLARINGER:
        return FORKLARINGER[status]
    if status >= 500:
        return f"Feil hos Munin ({status}): prøv igjen om litt. Vedvarer det, kontakt FHI med korrelasjons-id-en."
    return f"Uventet svar fra Munin ({status})."


def json_fra(svar: requests.Response) -> Any:
    """Kroppen i et vellykket svar som JSON, eller en MuninFeil når det ikke er JSON (for eksempel en HTML-side)."""
    try:
        return svar.json()
    except ValueError as feil:
        raise MuninFeil(f"Munin svarte {svar.status_code}, men ikke med JSON. Sjekk adressen i .env "
                        f"(fikk «{svar.headers.get('Content-Type', 'ukjent innholdstype')}»).", svar.status_code) from feil


def feil_fra_svar(svar: requests.Response) -> MuninFeil:
    """Lager en MuninFeil av et feilsvar, med API-ets egen tekst der den finnes."""
    korrelasjons_id = svar.headers.get("X-Correlation-ID")
    api_tekst = None
    detaljer: dict[str, Any] = {}
    try:
        kropp = svar.json()
    except ValueError:
        kropp = None
    if isinstance(kropp, dict):
        # Ingest svarer {"error", "correlationId", "details"}; andre ruter svarer
        # ProblemDetails {"title", "detail", "errors"}.
        api_tekst = kropp.get("error") or kropp.get("detail") or kropp.get("title")
        korrelasjons_id = kropp.get("correlationId") or korrelasjons_id
        detaljer = kropp.get("details") or kropp.get("errors") or {}
    elif svar.text and len(svar.text) < 500:
        api_tekst = svar.text.strip()

    melding = _forklaring(svar.status_code)
    if svar.status_code == 429 and svar.headers.get("Retry-After"):
        melding += f" API-et ber deg vente {svar.headers['Retry-After']} sekunder."
    if api_tekst:
        melding += f"\nMunin svarte: {api_tekst}"
    return MuninFeil(melding, svar.status_code, korrelasjons_id, detaljer)


@dataclass
class Innstillinger:
    """Det klienten trenger å vite. Hentes fra miljøet med `fra_miljo()`."""

    tenant_id: str
    client_id: str
    client_secret: str | None
    scope: str
    ingest_url: str = "https://ingest.munin.skytest.fhi.no"
    eksport_url: str = "https://export.munin.skytest.fhi.no"
    # Innlogging med sertifikat i stedet for hemmelighet: den private nøkkelen og sertifikatet
    # fra lag_sertifikat.py. Brukes når client_secret er tom.
    cert_nokkel_sti: str | None = None
    cert_sti: str | None = None

    @classmethod
    def fra_miljo(cls) -> "Innstillinger":
        """Leser innstillingene fra miljøvariabler (og fra .env, hvis python-dotenv finnes)."""
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass

        def verdi(navn: str) -> str | None:
            return os.environ.get(navn, "").strip() or None

        mangler = [navn for navn in ("MUNIN_TENANT_ID", "MUNIN_CLIENT_ID", "MUNIN_SCOPE") if not verdi(navn)]
        if not verdi("MUNIN_CLIENT_SECRET") and not (verdi("MUNIN_CERT_KEY_PATH") and verdi("MUNIN_CERT_PATH")):
            mangler.append("MUNIN_CERT_KEY_PATH og MUNIN_CERT_PATH (eller MUNIN_CLIENT_SECRET)")
        if mangler:
            raise MuninFeil(
                "Mangler innstillinger: " + ", ".join(mangler)
                + ". Kopier .env.example til .env og fyll inn verdiene du fikk fra FHI."
            )
        return cls(
            tenant_id=verdi("MUNIN_TENANT_ID"),
            client_id=verdi("MUNIN_CLIENT_ID"),
            client_secret=verdi("MUNIN_CLIENT_SECRET"),
            scope=verdi("MUNIN_SCOPE"),
            cert_nokkel_sti=verdi("MUNIN_CERT_KEY_PATH"),
            cert_sti=verdi("MUNIN_CERT_PATH"),
            ingest_url=os.environ.get("MUNIN_INGEST_URL", cls.ingest_url).strip().rstrip("/"),
            eksport_url=os.environ.get("MUNIN_EXPORT_URL", cls.eksport_url).strip().rstrip("/"),
        )


@dataclass
class TokenKilde:
    """Henter og husker et tilgangstoken fra Entra ID.

    Tokenet gjelder i om lag en time. Vi henter et nytt når det er under ett
    minutt igjen, så hvert kall slipper å hente sitt eget.
    """

    innstillinger: Innstillinger
    okt: requests.Session = field(default_factory=requests.Session)
    _token: str | None = None
    _utloper: float = 0.0

    def token(self) -> str:
        if self._token and time.time() < self._utloper - 60:
            return self._token

        adresse = f"https://login.microsoftonline.com/{self.innstillinger.tenant_id}/oauth2/v2.0/token"
        data = {
            "grant_type": "client_credentials",
            "client_id": self.innstillinger.client_id,
            "scope": self.innstillinger.scope,
        }
        if self.innstillinger.client_secret:
            data["client_secret"] = self.innstillinger.client_secret
        else:
            # Med sertifikat sender vi ingen hemmelighet, bare en kort påstand signert med den
            # private nøkkelen. Entra sjekker signaturen mot sertifikatet FHI har lastet opp.
            data["client_assertion_type"] = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
            data["client_assertion"] = klientpastand(self.innstillinger, adresse)
        try:
            svar = self.okt.post(adresse, data=data, timeout=STANDARD_TIDSAVBRUDD)
        except requests.RequestException as feil:
            raise MuninFeil(f"Fikk ikke kontakt med Entra ID for å hente token: {feil}") from feil

        if svar.status_code != 200:
            # Entra svarer {"error", "error_description"}; beskrivelsen starter med en
            # AADSTS-kode som forklarer feilen (for eksempel 7000215: feil hemmelighet).
            try:
                kropp = svar.json()
                beskrivelse = kropp.get("error_description", "").split("\r\n")[0]
            except ValueError:
                beskrivelse = svar.text[:300]
            raise MuninFeil(
                f"Entra ID ga ikke noe token ({svar.status_code}). Sjekk tenant-id, klient-id, scope og "
                f"sertifikatet (eller klienthemmeligheten) i .env. AADSTS700027 betyr at FHI ikke har lastet "
                f"opp dette sertifikatet ennå.\nEntra svarte: {beskrivelse}",
                svar.status_code,
            )

        kropp = json_fra(svar)
        if not isinstance(kropp, dict) or not kropp.get("access_token"):
            raise MuninFeil("Entra ID svarte uten noe token. Sjekk MUNIN_SCOPE i .env.")
        self._token = kropp["access_token"]
        # Minst to minutter, så et kort token ikke hentes på nytt ved hvert kall.
        self._utloper = time.time() + max(int(kropp.get("expires_in", 3600)), 120)
        return self._token

    def roller(self) -> list[str]:
        """Rollene tokenet gir, lest rett ut av tokenet. Nyttig når du får 403.

        Vi leser bare innholdet i tokenet; det er API-et som sjekker at det er ekte.
        """
        try:
            nyttelast = self.token().split(".")[1]
            nyttelast += "=" * (-len(nyttelast) % 4)
            data = json.loads(base64.urlsafe_b64decode(nyttelast))
        except (IndexError, ValueError) as feil:
            raise MuninFeil("Tokenet fra Entra ID kunne ikke leses.") from feil
        return sorted(data.get("roles", []))


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def klientpastand(innstillinger: Innstillinger, token_adresse: str) -> str:
    """En «client assertion»: en JWT signert med den private nøkkelen, gyldig i ti minutter.

    Hodet bærer sertifikatets fingeravtrykk (x5t#S256 og x5t), så Entra vet hvilket opplastet
    sertifikat signaturen skal sjekkes mot.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    try:
        nokkel = serialization.load_pem_private_key(Path(innstillinger.cert_nokkel_sti).read_bytes(), password=None)
        sertifikat = x509.load_pem_x509_certificate(Path(innstillinger.cert_sti).read_bytes())
    except (OSError, ValueError) as feil:
        raise MuninFeil(f"Kunne ikke lese nøkkelen eller sertifikatet ({feil}). Sjekk MUNIN_CERT_KEY_PATH og "
                        "MUNIN_CERT_PATH i .env, eller lag dem på nytt med lag_sertifikat.py.") from feil

    der = sertifikat.public_bytes(serialization.Encoding.DER)
    hode = {"alg": "RS256", "typ": "JWT",
            "x5t#S256": _b64url(hashlib.sha256(der).digest()), "x5t": _b64url(hashlib.sha1(der, usedforsecurity=False).digest())}
    nu = int(time.time())
    innhold = {"aud": token_adresse, "iss": innstillinger.client_id, "sub": innstillinger.client_id,
               "jti": str(uuid.uuid4()), "nbf": nu, "iat": nu, "exp": nu + 600}
    usignert = f"{_b64url(json.dumps(hode).encode())}.{_b64url(json.dumps(innhold).encode())}"
    signatur = nokkel.sign(usignert.encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{usignert}.{_b64url(signatur)}"


class _ApiKlient:
    """Felles kode for kall mot én av Munins API-er."""

    def __init__(self, base_url: str, tokens: TokenKilde | None, okt: requests.Session | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.tokens = tokens
        self.okt = okt or (tokens.okt if tokens else requests.Session())

    def _kall(self, metode: str, sti: str, *, autentisert: bool = True, tidsavbrudd: int = STANDARD_TIDSAVBRUDD,
              **argumenter: Any) -> requests.Response:
        hoder = argumenter.pop("headers", {})
        hoder.setdefault("Accept-Language", "nb")
        if autentisert:
            if self.tokens is None:
                raise MuninFeil("Dette kallet trenger et token, men klienten er laget uten innstillinger.")
            hoder["Authorization"] = f"Bearer {self.tokens.token()}"
        try:
            svar = self.okt.request(metode, self.base_url + sti, headers=hoder, timeout=tidsavbrudd, **argumenter)
        except requests.Timeout as feil:
            raise MuninFeil(f"Munin svarte ikke innen {tidsavbrudd} sekunder ({sti}).") from feil
        except requests.RequestException as feil:
            raise MuninFeil(f"Fikk ikke kontakt med Munin på {self.base_url}: {feil}") from feil
        if svar.status_code >= 400:
            raise feil_fra_svar(svar)
        return svar


class IngestKlient(_ApiKlient):
    """Ingest-API-et: skriv metadata til de kildene klienten har tilgang til."""

    def helse(self) -> dict[str, Any]:
        """Er API-et oppe, og når det identitetsleverandørene? Krever ikke token."""
        return json_fra(self._kall("GET", "/api/ingest/v1/health", autentisert=False))

    def kilder(self) -> list[dict[str, Any]]:
        """Kildene klienten har tilgang til (de med samme dataleverandør som rollen)."""
        return json_fra(self._kall("GET", "/api/ingest/v1/kilder"))

    def kilde(self, kilde_kode: str) -> dict[str, Any]:
        """Én kilde med alle detaljer."""
        return json_fra(self._kall("GET", f"/api/ingest/v1/kilder/{_sti(kilde_kode)}"))

    def lagre_variabel(self, kilde_kode: str, variabel_kode: str, foretrukket_term: str,
                       beskrivelse: str | None = None, **flere_felt: Any) -> tuple[int, dict[str, Any]]:
        """Oppretter variabelen, eller oppdaterer den hvis den finnes («upsert»).

        Returnerer statuskoden (201 = opprettet, 200 = oppdatert) og svaret.
        Bare feltene du sender, endres; de andre blir stående.
        """
        kropp: dict[str, Any] = {"preferredTerm": foretrukket_term, **flere_felt}
        if beskrivelse is not None:
            kropp["beskrivelse"] = beskrivelse
        svar = self._kall("PATCH", f"/api/ingest/v1/kilder/{_sti(kilde_kode)}/variabler/{_sti(variabel_kode)}",
                          json=kropp)
        return svar.status_code, json_fra(svar)


class EksportKlient(_ApiKlient):
    """Eksport-API-et: les publisert metadata."""

    def helse(self) -> dict[str, Any]:
        return json_fra(self._kall("GET", "/api/export/v1/health", autentisert=False))

    def healthdcat_katalog(self) -> dict[str, Any]:
        """HealthDCAT-AP-katalogen (v2, JSON-LD). Åpen, uten token, men stor (flere MB)."""
        return json_fra(self._kall("GET", "/api/export/v2/healthdcat-ap/catalog", autentisert=False,
                                   tidsavbrudd=KATALOG_TIDSAVBRUDD, headers={"Accept": "application/ld+json"}))

    def kildeliste(self, sidestorrelse: int = 100) -> list[dict[str, Any]]:
        """Alle kilder uten variabler (lett liste). Krever export.datasets.read."""
        return [element["kilde"] for element in
                self._sider("/api/export/v1/datasets", {"include": "kilde", "pageSize": sidestorrelse})]

    def datasett(self, kilde_kode: str) -> dict[str, Any]:
        """Én kilde med alle variabler, med variabellistene som koder. Krever export.datasets.read."""
        return json_fra(self._kall("GET", f"/api/export/v1/datasets/{_sti(kilde_kode)}",
                                   params={"nestedVariables": "codes"}))

    def variabler(self, kilde_kode: str) -> Iterator[dict[str, Any]]:
        """Variablene i én kilde, side for side. Krever export.metadata.read."""
        yield from self._sider("/api/export/v1/metadata/variables", {"kildeCode": kilde_kode})

    def variabel(self, kilde_kode: str, variabel_kode: str) -> list[dict[str, Any]]:
        """Radene for én variabel (én per datasamling den inngår i; tom liste når den ikke finnes)."""
        return [rad for rad in self.variabler(kilde_kode)
                if rad.get("code", "").casefold() == variabel_kode.casefold()]

    def _sider(self, sti: str, parametre: dict[str, Any]) -> Iterator[dict[str, Any]]:
        # Eksport deler lange lister i sider. Hver side har et «pageToken» for neste
        # side; det er null på den siste.
        side_token = None
        sett: set[str] = set()
        for _ in range(MAKS_SIDER):
            svar = self._kall("GET", sti, params={**parametre, **({"pageToken": side_token} if side_token else {})})
            data = json_fra(svar)
            yield from data.get("items", [])
            side_token = data.get("pageToken")
            if not side_token:
                return
            if side_token in sett:
                raise MuninFeil(f"Munin ga samme sidetoken to ganger ({sti}); stoppet for ikke å gå i ring.")
            sett.add(side_token)
        raise MuninFeil(f"Stoppet etter {MAKS_SIDER} sider ({sti}).")


def katalog_oversikt(katalog: dict[str, Any]) -> dict[str, Any]:
    """Det viktigste i HealthDCAT-AP-katalogen: tittelen, seriene (én per kilde) og antall datasett.

    I v2 er hver kilde en «dcat:datasetSeries» og hver datasamling et «dcat:dataset».
    """
    def tekst(verdi: Any) -> str:
        # En tekst i JSON-LD er {"@language": "nb", "@value": "..."}, eller en liste av slike.
        if isinstance(verdi, list):
            norsk = [v for v in verdi if isinstance(v, dict) and v.get("@language") in ("nb", "no")]
            verdi = (norsk or verdi or [""])[0]
        return verdi.get("@value", "") if isinstance(verdi, dict) else str(verdi or "")

    serier = [{"kode": tekst(s.get("dct:identifier")), "tittel": tekst(s.get("dct:title"))}
              for s in katalog.get("dcat:datasetSeries", [])]
    return {"tittel": tekst(katalog.get("dct:title")), "serier": serier,
            "antall_datasett": len(katalog.get("dcat:dataset", []))}


def _sti(kode: str) -> str:
    """En kode trygt satt inn i en URL-sti (en kode med / eller ? kan ikke ødelegge adressen)."""
    return quote(kode.strip(), safe="")


def lag_klienter(innstillinger: Innstillinger | None = None) -> tuple[IngestKlient, EksportKlient, TokenKilde]:
    """Lager begge klientene med ett felles token (samme app-registrering gir tilgang til begge)."""
    innstillinger = innstillinger or Innstillinger.fra_miljo()
    tokens = TokenKilde(innstillinger)
    return (IngestKlient(innstillinger.ingest_url, tokens),
            EksportKlient(innstillinger.eksport_url, tokens),
            tokens)
