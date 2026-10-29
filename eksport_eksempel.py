"""Eksport-API-et steg for steg, i terminalen.

Kjør:  python eksport_eksempel.py [kildekode]

Skriptet henter den åpne HealthDCAT-AP-katalogen (uten token), lister alle
kilder og viser én kilde med variablene sine.
"""

from __future__ import annotations

import sys

from munin_api import MuninFeil, katalog_oversikt, lag_klienter


def main() -> int:
    kilde_kode = sys.argv[1] if len(sys.argv) > 1 else None

    try:
        _, eksport, tokens = lag_klienter()

        # 1. Den åpne katalogen. Den er stor, så dette kan ta et halvt minutt.
        katalog = eksport.healthdcat_katalog()
        oversikt = katalog_oversikt(katalog)
        print(f"1. HealthDCAT-AP-katalogen «{oversikt['tittel']}» har {len(oversikt['serier'])} kilder "
              f"og {oversikt['antall_datasett']} datasamlinger.")

        # 2. Token. Rollene i tokenet bestemmer hva du får lese.
        print(f"2. Token hentet. Roller: {', '.join(tokens.roller()) or '(ingen)'}")

        # 3. Alle kilder, uten variabler.
        kilder = eksport.kildeliste()
        print(f"3. Eksport har {len(kilder)} kilde(r):")
        for kilde in kilder[:20]:
            print(f"   - {kilde['code']}: {kilde.get('preferredTerm')}")

        # 4. Én kilde med alle variabler.
        kilde_kode = kilde_kode or (kilder[0]["code"] if kilder else None)
        if kilde_kode:
            datasett = eksport.datasett(kilde_kode)
            variabler = datasett.get("variabler", [])
            print(f"4. {kilde_kode} har {len(variabler)} variabel(er) og "
                  f"{len(datasett.get('kilde', {}).get('datasamlinger', []))} datasamling(er) direkte under kilden.")
            for variabel in variabler[:10]:
                print(f"   - {variabel.get('code')}: {variabel.get('preferredTerm') or variabel.get('name')}")
        return 0
    except MuninFeil as feil:
        print(f"\nFeil: {feil}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
