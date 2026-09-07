"""
Generate a self-signed TLS certificate so Safari on the iPad will allow the
microphone (it requires HTTPS / a secure context).

Usage:
    pip install cryptography
    python make_cert.py 10.10.124.76          # pass your PC's LAN IP
    # -> writes certs/cert.pem and certs/key.pem

The IP(s) you pass are added to the certificate's Subject Alternative Names,
along with localhost / 127.0.0.1, so the cert is valid for both PC and iPad use.
"""

import datetime
import ipaddress
import os
import sys

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

OUT_DIR = "certs"


def main(ip_args: list[str]) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)

    # Build SAN list: always localhost + loopback, plus any IPs passed in.
    san = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    for ip in ip_args:
        try:
            san.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            san.append(x509.DNSName(ip))  # allow hostnames too

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Zeta Voice Chat")])
    now = datetime.datetime.utcnow()
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .sign(key, hashes.SHA256())
    )

    with open(os.path.join(OUT_DIR, "key.pem"), "wb") as f:
        f.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ))
    with open(os.path.join(OUT_DIR, "cert.pem"), "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    print("Wrote certs/cert.pem and certs/key.pem")
    print("SAN entries:", ["localhost", "127.0.0.1", *ip_args])


if __name__ == "__main__":
    main(sys.argv[1:] or ["10.10.124.76"])
