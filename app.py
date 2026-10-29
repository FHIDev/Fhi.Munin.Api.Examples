"""En nettside for Munins API-er, laget med Streamlit.

Start:  streamlit run app.py
Siden åpner seg i nettleseren. All logikk ligger i munin_api.py; denne filen
viser bare knapper, felt og tabeller.
"""

from __future__ import annotations

import time

import streamlit as st

from munin_api import EksportKlient, Innstillinger, MuninFeil, katalog_oversikt, lag_klienter

st.set_page_config(page_title="Munin API-eksempler", layout="wide")
st.title("Munin API-eksempler")


@st.cache_resource
def klienter():
    """Lager klientene én gang per økt, så tokenet gjenbrukes mellom knappetrykk."""
    return lag_klienter(Innstillinger.fra_miljo())


def vis_feil(feil: MuninFeil) -> None:
    st.error(feil.melding)
    if feil.detaljer:
        st.table([{"Felt": navn, "Feil": ", ".join(map(str, verdi)) if isinstance(verdi, list) else verdi}
                  for navn, verdi in feil.detaljer.items()])
    if feil.korrelasjons_id:
        st.caption(f"Korrelasjons-id (oppgi den til FHI): {feil.korrelasjons_id}")


try:
    ingest, eksport, tokens = klienter()
except MuninFeil as feil:
    vis_feil(feil)
    st.info("Siden trenger en .env-fil. Se README.md, avsnittet «Sett opp tilgangen».")
    st.stop()

with st.sidebar:
    st.header("Tilkobling")
    st.write(f"Ingest: `{ingest.base_url}`")
    st.write(f"Eksport: `{eksport.base_url}`")
    if st.button("Vis rollene i tokenet"):
        try:
            roller = tokens.roller()
            st.success("Token hentet.")
            st.table([{"Rolle": rolle} for rolle in roller] or [{"Rolle": "(ingen roller)"}])
        except MuninFeil as feil:
            vis_feil(feil)

fane_ingest, fane_eksport = st.tabs(["Ingest (skrive)", "Eksport (lese)"])

with fane_ingest:
    kilde_kode = st.text_input("Kildekode", value="test", key="ingest_kilde")
    variabel_kode = st.text_input("Variabelkode", value="EKSEMPEL_VARIABEL")
    foretrukket_term = st.text_input("Navn (preferredTerm)", value="Eksempelvariabel")
    beskrivelse = st.text_area("Beskrivelse", value="Lagret fra eksempelsiden.")

    kolonner = st.columns(4)
    if kolonner[0].button("Helsesjekk"):
        try:
            helse = ingest.helse()
            (st.success if helse["status"] == "healthy" else st.warning)(
                f"Status: {helse['status']}, API-versjon {helse['version']['major']}.{helse['version']['minor']}")
            st.table([{"Identitetsleverandør": s["scheme"], "Status": s["status"]}
                      for s in helse.get("authentication", {}).get("schemes", [])])
        except MuninFeil as feil:
            vis_feil(feil)

    if kolonner[1].button("Mine kilder"):
        try:
            kilder = ingest.kilder()
            st.write(f"Du har tilgang til {len(kilder)} kilde(r).")
            st.dataframe([{"Kode": k["code"], "Navn": k.get("preferredTerm"), "Dataleverandør": k.get("dataleverandorNavn"),
                           "Verifisert": k.get("verifisert"), "Aktiv": k.get("enabled")} for k in kilder],
                         width="stretch")
        except MuninFeil as feil:
            vis_feil(feil)

    if kolonner[2].button("Lagre variabel"):
        try:
            status, svar = ingest.lagre_variabel(kilde_kode, variabel_kode, foretrukket_term, beskrivelse or None)
            variabel = svar["variabel"]
            st.success(f"Variabelen ble {'opprettet' if status == 201 else 'oppdatert'} ({status}).")
            versjon = variabel.get("activeVersjon") or {}
            st.table([{"Kode": variabel["code"], "Id": variabel["id"], "Navn": versjon.get("preferredTerm"),
                       "Beskrivelse": versjon.get("beskrivelse"), "Status": versjon.get("status")}])
        except MuninFeil as feil:
            vis_feil(feil)

    if kolonner[3].button("Les tilbake (Eksport)"):
        try:
            rader = eksport.variabel(kilde_kode, variabel_kode)
            if rader:
                st.dataframe([{"Kode": r.get("code"), "Navn": r.get("name"), "Beskrivelse": r.get("description"),
                               "Datasamling": r.get("datasamlingCode") or "(ingen)", "Versjon": r.get("versjonCode"),
                               "Sist endret": r.get("lastChangedUtc")} for r in rader], width="stretch")
            else:
                st.warning("Eksport viser ikke variabelen ennå. Eksport kan ligge litt etter; prøv igjen om et minutt.")
        except MuninFeil as feil:
            vis_feil(feil)

with fane_eksport:
    st.write("Katalogen er åpen. Kildelisten og datasettet krever rollen export.datasets.read.")
    kolonner = st.columns(3)

    if kolonner[0].button("HealthDCAT-katalogen"):
        try:
            with st.spinner("Henter katalogen (den er stor, så det kan ta et halvt minutt) ..."):
                start = time.time()
                katalog = EksportKlient(eksport.base_url, None).healthdcat_katalog()
            oversikt = katalog_oversikt(katalog)
            st.success(f"«{oversikt['tittel']}»: {len(oversikt['serier'])} kilder (serier) og "
                       f"{oversikt['antall_datasett']} datasamlinger (datasett), hentet på {time.time() - start:.0f} sekunder.")
            st.dataframe([{"Kode": s["kode"], "Tittel": s["tittel"]} for s in oversikt["serier"]],
                         width="stretch")
        except MuninFeil as feil:
            vis_feil(feil)

    if kolonner[1].button("Alle kilder"):
        try:
            kilder = eksport.kildeliste()
            st.write(f"{len(kilder)} kilde(r).")
            st.dataframe([{"Kode": k["code"], "Navn": k.get("preferredTerm"), "Type": k.get("kildetype"),
                           "Variabler": k.get("variabelCount")} for k in kilder], width="stretch")
        except MuninFeil as feil:
            vis_feil(feil)

    eksport_kilde = kolonner[2].text_input("Kildekode for datasett", value="test", key="eksport_kilde")
    if kolonner[2].button("Vis datasett"):
        try:
            datasett = eksport.datasett(eksport_kilde)
            variabler = datasett.get("variabler", [])
            st.write(f"{len(variabler)} variabel(er).")
            st.dataframe([{"Kode": v.get("code"), "Navn": v.get("preferredTerm"), "Beskrivelse": v.get("beskrivelse"),
                           "Kodeverk": ", ".join(f"{k.get('kodeverkType')}: {k.get('kodeverkReference')}"
                                                 for k in v.get("kodeverklinker", []))}
                          for v in variabler], width="stretch")
            st.subheader("Datasamlinger og variablene deres")
            st.dataframe([{"Datasamling": d.get("code"), "Navn": d.get("preferredTerm"),
                           "Variabler": ", ".join(d.get("variabler", []))}
                          for d in datasett.get("kilde", {}).get("datasamlinger", [])], width="stretch")
        except MuninFeil as feil:
            vis_feil(feil)
