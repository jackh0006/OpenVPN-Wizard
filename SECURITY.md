# Security policy

## Supported versions

| Version | Status |
|---|---|
| 2.x | ✅ supported |
| 1.x | ❌ unsupported (hardcoded credentials, destructive HAProxy rewrite) |

## Reporting a vulnerability

Email **jackh109867@gmail.com** with:

* description and impact,
* reproduction steps,
* affected version,
* suggested fix if you have one.

Acknowledgment within 48 hours; investigation within 5 business days; a patch
as soon as it is tested. Good-faith researchers will be credited.

## v2 security controls

| Area | Implementation |
|---|---|
| Data encryption | AES-256-GCM / CHACHA20-POLY1305 / AES-128-GCM (AEAD) |
| Control channel | TLS 1.2 minimum, TLS 1.3 when available, `tls-crypt` |
| Integrity | SHA-256 / AEAD tags |
| Certificates | ECDSA P-384; 10-year CA; 825-day leaves |
| Revocation | Real CRL, regenerated on every revocation, enforced by OpenVPN |
| Authentication | Unique certificate + optional PAM password |
| Password hashing | PBKDF2-HMAC-SHA256, 600,000 iterations |
| Compression | Disabled |
| Profile delivery | SSH/SCP or one-time token HTTPS; never HTTP |
| File permissions | PKI private dir 700, keys 600, profiles 600, DB 600 |
| Logging | Rotated file, password patterns redacted |
| Telemetry | None |

### Deliberate non-goals

* Guaranteed invisibility to every DPI system. TCP/443 + `tls-crypt` is
  robust, but active protocol blocking can still succeed.
* Protecting data from the VPS provider, which terminates the tunnel.
* Hiding metadata such as connection times or traffic volume.

## No secrets in source

v2 contains no server IP, username, password or private key. The test suite
generates throwaway certificates in temporary directories. If you find a
committed key, treat it as a vulnerability and report it.

## File permissions

| Path | Mode |
|---|---|
| `/etc/openvpn/pki/private/` | 700 |
| `/etc/openvpn/pki/private/*.key` | 600 |
| `/etc/openvpn/clients/` | 700 |
| `/etc/openvpn/clients/*.ovpn` | 600 |
| `/root/openvpn-wizard-credentials.txt` | 600 |
| `/etc/openvpn/users.db` | 600 |
| `/var/log/vpn-installer/install.log` | 600 |

## Responsible disclosure

Do not access other users' data, disrupt service, or publish details before a
fix is available. Good-faith research following this policy will not lead to
legal action from the maintainers.
