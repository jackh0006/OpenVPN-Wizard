# OpenVPN Wizard v2.2.0 — smarter endpoint and port setup

## Safer choices before installation

- A selected domain is resolved before installation. The wizard tells you if
  it points to this VPS, then asks whether to keep it or use the server IP.
- No domain is required: choosing the server IP produces a complete, secure
  OpenVPN setup without DNS or a certificate dependency.
- Public ports are checked for both TCP and UDP. Occupied ports show their
  listener information and the wizard suggests free alternatives.
- The selected port remains fully configurable with `--port`; a TCP/HAProxy
  backend can also use `--internal-port`.

## Reliability and security

- An unrelated listener is refused before OpenVPN configuration changes or a
  service restart. The wizard never kills another process.
- Manual passwords accept any practical non-empty value; generated passwords
  remain long, random, and the recommended default.
- Existing cryptographic defaults remain unchanged: AEAD data ciphers, TLS
  1.3 by default, ECDSA P-384 certificates, `tls-crypt`, per-user identities,
  CRL enforcement, and no compression.

## Verification

- Python compilation and the full pytest suite pass.
- Existing HAProxy, OpenVPN, firewall, PKI, dry-run, and profile tests remain
  in place and run in CI.
