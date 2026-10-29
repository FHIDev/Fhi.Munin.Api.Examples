"""Lager et nøkkelpar og et selvsignert sertifikat for innlogging uten hemmelighet.

Kjør:  python lag_sertifikat.py

- Den private nøkkelen lagres i mappen .munin i brukermappen din, som andre vanlige brukere ikke
  har tilgang til. Den forlater aldri maskinen din. Ikke send den til noen.
- Sertifikatet (den offentlige delen) lagres som munin-klient.cer i denne mappen. Det er ikke
  hemmelig: send det til FHI, som laster det opp på app-registreringen din.

Skriptet skriver ut linjene du skal lime inn i .env.
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

NOKKELMAPPE = Path.home() / ".munin"
NOKKELFIL = NOKKELMAPPE / "munin-klient.key"
SERTIFIKATFIL = Path(__file__).resolve().parent / "munin-klient.cer"


def lag(navn: str, gyldig_dager: int, nokkelfil: Path, sertifikatfil: Path, erstatt: bool = False) -> None:
    """Lager nøkkel og sertifikat. Begge skrives først under midlertidige navn og byttes inn til slutt,
    så en feil underveis aldri etterlater en nøkkel uten sertifikat eller tar fra deg nøkkelen du har."""
    if nokkelfil.exists() and not erstatt:
        raise FileExistsError(nokkelfil)
    nokkel = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    nu = datetime.datetime.now(datetime.timezone.utc)
    subjekt = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, navn)])
    sertifikat = (
        x509.CertificateBuilder()
        .subject_name(subjekt)
        .issuer_name(subjekt)  # selvsignert: utsteder og eier er den samme
        .public_key(nokkel.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(nu - datetime.timedelta(minutes=5))
        .not_valid_after(nu + datetime.timedelta(days=gyldig_dager))
        .sign(nokkel, hashes.SHA256())
    )

    # Nøkkelfilen lages med rettigheter bare for deg (på Windows er hjemmemappen din allerede bare din).
    nokkelfil.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(nokkelfil.parent, 0o700)
    pem = nokkel.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                               serialization.NoEncryption())
    ny_nokkel = nokkelfil.with_name(nokkelfil.name + ".ny")
    nytt_sertifikat = sertifikatfil.with_name(sertifikatfil.name + ".ny")
    try:
        ny_nokkel.unlink(missing_ok=True)
        fd = os.open(ny_nokkel, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fil:
            fil.write(pem)
        nytt_sertifikat.write_bytes(sertifikat.public_bytes(serialization.Encoding.PEM))
        os.replace(nytt_sertifikat, sertifikatfil)
        os.replace(ny_nokkel, nokkelfil)
    finally:
        ny_nokkel.unlink(missing_ok=True)
        nytt_sertifikat.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Lag nøkkelpar og sertifikat for Munin-innlogging.")
    parser.add_argument("--navn", default="munin-api-eksempler", help="navnet i sertifikatet (CN)")
    parser.add_argument("--dager", type=int, default=365, help="hvor mange dager sertifikatet gjelder")
    parser.add_argument("--ny", action="store_true", help="erstatt en nøkkel du har fra før")
    argumenter = parser.parse_args()

    if NOKKELFIL.exists() and not argumenter.ny:
        print(f"Du har allerede en nøkkel: {NOKKELFIL}\n"
              "Bruk --ny for å lage en ny. Da må FHI laste opp det nye sertifikatet.")
        return 1

    lag(argumenter.navn, argumenter.dager, NOKKELFIL, SERTIFIKATFIL, erstatt=argumenter.ny)
    print("Ferdig.\n")
    if argumenter.ny:
        print("Den gamle nøkkelen er erstattet. Send det nye sertifikatet til FHI, og be dem fjerne det gamle.\n")
    print(f"Privat nøkkel (hemmelig, blir på maskinen din): {NOKKELFIL}")
    print(f"Sertifikat (ikke hemmelig, send det til FHI):  {SERTIFIKATFIL}\n")
    print("Lim inn disse to linjene i .env, og la MUNIN_CLIENT_SECRET stå tom:")
    # I enkle anførselstegn, så et mellomrom eller # i stien ikke ødelegger linjen.
    print(f"MUNIN_CERT_KEY_PATH='{NOKKELFIL}'")
    print(f"MUNIN_CERT_PATH='{SERTIFIKATFIL}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
