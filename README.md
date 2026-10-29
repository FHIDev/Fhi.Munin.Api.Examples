# Munin API-eksempler

Små, fungerende eksempler på hvordan du snakker med Munin, FHIs metadatakatalog for helsedata, fra Python:

- **Ingest-API-et** skriver metadata: lagre en variabel i en kilde du har tilgang til.
- **Eksport-API-et** leser metadata: den åpne HealthDCAT-AP-katalogen, listen over kilder og én kilde med alle variablene sine.

Du kan bruke eksemplene på to måter:

- **I nettleseren**, med en enkel side (Streamlit) med felt, knapper og tabeller.
- **I terminalen**, med to korte skript som går gjennom stegene ett for ett.

Begge bruker den samme lille modulen, `munin_api.py`. Den kan du også ta med inn i egne skript.

Eksemplene går mot Munins **testmiljø**. Bruk en testkilde: det du lagrer, blir liggende i testkatalogen.

English summary: [at the end](#english).

---

## Innhold

1. [Hva du trenger](#1-hva-du-trenger)
2. [Installer](#2-installer)
3. [Sett opp tilgangen](#3-sett-opp-tilgangen)
4. [Kjør nettsiden](#4-kjør-nettsiden)
5. [Kjør i terminalen](#5-kjør-i-terminalen)
6. [Hva skjer i hvert steg](#6-hva-skjer-i-hvert-steg)
7. [Når noe går galt](#7-når-noe-går-galt)
8. [Bruk modulen i egne skript](#8-bruk-modulen-i-egne-skript)
9. [For utviklere: testene](#9-for-utviklere-testene)

---

## 1. Hva du trenger

- **Python 3.11 eller nyere.** Sjekk med `python --version` (på Windows også `py --version`).
- **Tilgang fra FHI:** en app-registrering i FHIs Entra ID med de rollene du skal bruke (se avsnitt 3).
- Denne mappen, lastet ned eller klonet.

## 2. Installer

Åpne en terminal i denne mappen og lag et eget Python-miljø for prosjektet, så pakkene ikke blandes med andre prosjekter.

**Windows (PowerShell):**

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Sier PowerShell at skript er blokkert, kjør først `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` og prøv igjen.

**macOS og Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Neste gang trenger du bare aktiveringslinjen (den andre linjen) før du kjører noe. Kommandoene under virker bare med miljøet aktivert og med terminalen i denne mappen.

## 3. Sett opp tilgangen

Munins API-er er for maskiner, ikke for innloggede personer. Du logger derfor ikke inn med brukeren din. I stedet bruker skriptet en **app-registrering**: en «maskinbruker» som FHI lager og eier. Skriptet beviser at det er app-registreringen din, henter et token, og tokenet bærer rollene som bestemmer hva du får gjøre:

| Rolle | Gir tilgang til |
|-------|-----------------|
| `ingest.provider.<dataleverandør>` | Skrive til kildene som har denne dataleverandøren |
| `export.metadata.read` | Lese variabler gjennom Eksport (brukes til «les tilbake») |
| `export.datasets.read` | Lese kildelisten og hele datasett gjennom Eksport |

### Med sertifikat (anbefalt)

Med et sertifikat finnes det ingen hemmelighet som må sendes noe sted. Du lager et nøkkelpar på din egen maskin. Den private nøkkelen blir der; FHI får bare sertifikatet, som er den offentlige delen.

1. Kjør `python lag_sertifikat.py`.
   - Den private nøkkelen havner i mappen `.munin` i hjemmemappen din, og bare du kan lese den. Ikke send den til noen.
   - Sertifikatet havner i denne mappen, som `munin-klient.cer`.
   - Skriptet skriver ut to linjer for `.env`. La vinduet stå åpent.
2. Send `munin-klient.cer` til FHI (Teams eller e-post går fint; det er ikke hemmelig). FHI laster det opp på app-registreringen din.
3. Du får tre verdier tilbake fra FHI: **tenant-id**, **klient-id** og **scope**. Heller ikke de er hemmelige.
4. Kopier `.env.example` til en ny fil som heter `.env`, i samme mappe. Fyll inn de tre verdiene, og lim inn de to linjene fra trinn 1 (`MUNIN_CERT_KEY_PATH` og `MUNIN_CERT_PATH`). La `MUNIN_CLIENT_SECRET` stå tom.

Sertifikatet gjelder i et år. Lag et nytt med `python lag_sertifikat.py --ny` og send det til FHI på samme måte.

### Med klienthemmelighet (alternativ)

En app-registrering kan også bruke en klienthemmelighet i stedet for et sertifikat. Da må hemmeligheten overføres trygt fra den som lager den, og aldri på e-post, Teams eller chat. Fyll den inn som `MUNIN_CLIENT_SECRET` i `.env`, og la de to sertifikatlinjene stå tomme. Er begge satt, brukes hemmeligheten.

`.env` står i `.gitignore`, så den havner ikke i git. Ingen hemmeligheter står i koden.

## 4. Kjør nettsiden

```
streamlit run app.py
```

Første gang spør Streamlit om e-postadressen din i terminalen. Trykk bare Enter. Siden åpner seg i nettleseren (ellers åpne adressen terminalen viser, vanligvis http://localhost:8501). Stopp den med Ctrl+C i terminalen.

Kjør siden bare på din egen maskin. Den bruker din app-registrering, så alle som når siden, skriver til Munin som deg.

**Hvilken kilde?** Trykk «Mine kilder» først, og bruk en kildekode fra den listen. Du kan bare skrive til kildene med samme dataleverandør som rollen din. Bruk en testkilde, siden det du lagrer, blir liggende i testkatalogen.

Siden har to faner:

- **Ingest (skrive):** fyll inn kildekode, variabelkode, navn og beskrivelse. Knappene er **Helsesjekk**, **Mine kilder**, **Lagre variabel** og **Les tilbake (Eksport)**.
- **Eksport (lese):** **HealthDCAT-katalogen** (åpen, uten token), **Alle kilder**, og **Vis datasett** for én kilde, med variablene og datasamlingene.

I sidemenyen viser **Vis rollene i tokenet** hvilke roller tokenet ditt faktisk har. Se der først når du får 403.

## 5. Kjør i terminalen

```
python ingest_eksempel.py <kildekode> [variabelkode]
python eksport_eksempel.py [kildekode]
```

For eksempel `python ingest_eksempel.py test EKSEMPEL_VARIABEL`. Skriptene skriver ut hvert steg med resultatet.

## 6. Hva skjer i hvert steg

**Ingest**

1. **Helsesjekk:** `GET /api/ingest/v1/health`. Krever ikke token. Svarer om API-et er oppe og om det når identitetsleverandørene (Entra ID og Maskinporten).
2. **Token:** skriptet beviser overfor Entra ID at det er app-registreringen din, med en kort påstand signert med den private nøkkelen (eller med hemmeligheten), og får et tilgangstoken tilbake (`client credentials`). Tokenet varer i om lag en time, og modulen henter et nytt selv.
3. **Mine kilder:** `GET /api/ingest/v1/kilder`. Kildene med samme dataleverandør som rollen din.
4. **Lagre variabel:** `PATCH /api/ingest/v1/kilder/{kilde}/variabler/{variabel}`. Finnes variabelen, oppdateres den (svar 200); ellers opprettes den (201). Bare feltene du sender, endres. Hver lagring lager en ny versjon av variabelen.
5. **Les tilbake:** `GET /api/export/v1/metadata/variables?kildeCode={kilde}` i Eksport-API-et, der andre systemer leser katalogen. Eksport kan ligge litt etter en lagring; vises ikke variabelen, prøv igjen om et minutt.

**Eksport**

1. **HealthDCAT-katalogen:** `GET /api/export/v2/healthdcat-ap/catalog`. Åpen for alle, i formatet helsedata.no og EUs katalog bruker. Den er stor (over 20 MB), så den tar litt tid.
2. **Alle kilder:** `GET /api/export/v1/datasets?include=kilde`. En lett liste uten variabler.
3. **Ett datasett:** `GET /api/export/v1/datasets/{kilde}?nestedVariables=codes`. Kilden med alle variabler, kodeverkkoblinger og datasamlinger. Datasamlingene viser variablene sine som koder.

Hele API-beskrivelsen står i Munins brukerveiledninger for Ingest- og Eksport-API-et, som FHI kan sende deg.

## 7. Når noe går galt

Modulen gjør hvert feilsvar om til en norsk forklaring, og tar med Munins egen tekst og en **korrelasjons-id**. Oppgi korrelasjons-id-en når du spør FHI om hjelp: med den finner de kallet i loggene.

| Kode | Betyr | Gjør dette |
|------|-------|------------|
| Entra-feil (AADSTS…) | Fikk ikke token | Sjekk tenant-id, klient-id, scope og sertifikatlinjene (eller hemmeligheten) i `.env`. AADSTS700027 betyr at FHI ikke har lastet opp sertifikatet ennå; AADSTS7000215 betyr feil hemmelighet; AADSTS700016 betyr ukjent klient-id. |
| 400 | Ugyldig forespørsel | Les feltfeilene. Et påkrevd felt mangler, eller en verdi er for lang. |
| 401 | Ikke autentisert | Tokenet mangler, er utløpt eller er utstedt for feil API. Sjekk `MUNIN_SCOPE`. |
| 403 | Ingen tilgang | Tokenet mangler rollen. Se «Vis rollene i tokenet», og sjekk at kilden har samme dataleverandør som rollen. |
| 404 | Ikke funnet | Kildekoden finnes ikke (store og små bokstaver teller), eller API-et er ikke slått på. |
| 409 | Konflikt | En annen endring kom i veien, eller noe du endrer, brukes også av en annen kilde. Prøv igjen; ved delte entiteter, kontakt FHI. |
| 413 | For stor forespørsel | Over om lag 30 MB. Del opp. |
| 429 | For mange forespørsler | Vent det antall sekunder svaret oppgir. |
| 5xx | Feil hos Munin | Prøv igjen om litt. Vedvarer det, kontakt FHI med korrelasjons-id-en. |

## 8. Bruk modulen i egne skript

```python
from munin_api import MuninFeil, lag_klienter

ingest, eksport, tokens = lag_klienter()  # leser .env

try:
    status, svar = ingest.lagre_variabel("test", "MIN_VARIABEL", "Min variabel", "En beskrivelse")
    print(status, svar["variabel"]["id"])
    print(eksport.variabel("test", "MIN_VARIABEL"))
except MuninFeil as feil:
    print(feil)  # norsk forklaring, feltfeil og korrelasjons-id
```

`lagre_variabel` tar også andre felt API-et kjenner, som nøkkelord, for eksempel `gyldigFra="2020-01-01T00:00:00Z"`. Bruk API-ets egne feltnavn, som `gyldigFra`: et navn som `gyldig_fra` sendes som det er, og API-et kjenner det ikke.

## 9. For utviklere: testene

Testene kjører uten nettverk: hvert HTTP-kall erstattes av et ferdig svar.

```
pip install -r requirements-dev.txt
python -m pytest
```

---

## English

Small working Python examples for Munin, the Norwegian Institute of Public Health's metadata catalogue for health data: the **Ingest API** (write metadata) and the **Export API** (read metadata), against the test environment.

- `munin_api.py` is a small client: an Entra ID client-credentials token (certificate or secret), both APIs, and every error turned into one exception type with a Norwegian explanation and the correlation id.
- `app.py` is a Streamlit page (`streamlit run app.py`).
- `ingest_eksempel.py` and `eksport_eksempel.py` are terminal walkthroughs.

Setup: `pip install -r requirements.txt`, then `python lag_sertifikat.py`, which creates a key pair: the private key stays on your machine, and you send the public certificate (`munin-klient.cer`) to FHI, who uploads it to your app registration (a client secret works too). Copy `.env.example` to `.env` and fill in the tenant id, client id and scope you get from FHI, plus the two certificate lines the script prints. No ids or secrets are in the code. Access is granted per data provider (`ingest.provider.<provider>`) and for export (`export.metadata.read`, `export.datasets.read`). Run the tests with `pip install -r requirements-dev.txt` and `python -m pytest`.

Licence: MIT, see [LICENSE](LICENSE).
