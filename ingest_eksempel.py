"""Ingest-API-et steg for steg, i terminalen.

Kjør:  python ingest_eksempel.py <kildekode> [variabelkode]

Skriptet sjekker at API-et er oppe, viser kildene du har tilgang til, lagrer
en variabel i kilden og leser den tilbake gjennom Eksport-API-et.
"""

from __future__ import annotations

import sys
import time

from munin_api import MuninFeil, lag_klienter


def main() -> int:
    if len(sys.argv) < 2:
        print("Bruk: python ingest_eksempel.py <kildekode> [variabelkode]")
        return 2
    kilde_kode = sys.argv[1]
    variabel_kode = sys.argv[2] if len(sys.argv) > 2 else "EKSEMPEL_VARIABEL"

    try:
        ingest, eksport, tokens = lag_klienter()

        # 1. Helsesjekk. Krever ikke token, så den virker selv om tilgangen ikke er på plass ennå.
        helse = ingest.helse()
        print(f"1. Helse: {helse['status']} (API-versjon {helse['version']['major']}.{helse['version']['minor']})")

        # 2. Token. Rollene i tokenet bestemmer hva du får lov til.
        print(f"2. Token hentet. Roller: {', '.join(tokens.roller()) or '(ingen)'}")

        # 3. Kildene du har tilgang til.
        kilder = ingest.kilder()
        print(f"3. Du har tilgang til {len(kilder)} kilde(r):")
        for kilde in kilder:
            print(
                f"   - {kilde['code']}: {kilde.get('preferredTerm')} (dataleverandør {kilde.get('dataleverandorNavn')})"
            )

        # 4. Lagre en variabel. Finnes den, oppdateres den (200); ellers opprettes den (201).
        status, svar = ingest.lagre_variabel(
            kilde_kode,
            variabel_kode,
            foretrukket_term="Eksempelvariabel",
            beskrivelse=f"Lagret av ingest_eksempel.py {time.strftime('%Y-%m-%d %H:%M')}",
        )
        hva = "opprettet" if status == 201 else "oppdatert"
        print(f"4. Variabelen {variabel_kode} ble {hva} ({status}). Id: {(svar.get('variabel') or {}).get('id')}")

        # 5. Les den tilbake gjennom Eksport-API-et, som er det andre systemer leser fra.
        rader = eksport.variabel(kilde_kode, variabel_kode)
        if rader:
            print(f"5. Lest tilbake fra Eksport: {rader[0].get('name')!r}, «{rader[0].get('description')}»")
        else:
            print("5. Eksport viser ikke variabelen ennå. Eksport kan ligge litt etter; prøv igjen om et minutt.")
        return 0
    except MuninFeil as feil:
        print(f"\nFeil: {feil}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
