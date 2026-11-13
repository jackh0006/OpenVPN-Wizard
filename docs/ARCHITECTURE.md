# Architecture (v2)

```
Client (OpenVPN Connect / openvpn CLI)
   │
   │  TCP/443 (or UDP/<port>)
   ▼
┌──────────────────────────────────────────────────────────────┐
│ HAProxy (only when TCP + HAProxy enabled)                    │
│  frontend ovpn_wizard_frontend_<port>  bind *:<port>         │
│    ├─ TLS ClientHello + known SNI → optional VLESS/Reality   │
│    └─ anything else               → 127.0.0.1:1194           │
└──────────────────────────────────────────────────────────────┘
   │
   ▼
OpenVPN (127.0.0.1:1194 when behind HAProxy, public port otherwise)
   │
   ├─ AEAD data channel (AES-256-GCM / CHACHA20-POLY1305)
   ├─ TLS 1.2+ control channel with tls-crypt
   ├─ unique ECDSA P-384 certificate per user + CRL
   └─ PAM password (optional second factor)
   │
   ▼
tun0 → NAT/forwarding (free mode) or no forwarding (locked mode)
```

## Design rules

1. **Only own your files.** The installer writes `/etc/openvpn/*` and a marked
   block in `/etc/haproxy/haproxy.cfg`. It never replaces an entire config.
2. **Validate before activating.** `haproxy -c` runs before reload; OpenVPN is
   restarted with a timestamped backup and rolled back on failure.
3. **One identity per user.** Each profile has its own certificate and key.
   Revoking one does not affect anyone else.
4. **No plaintext delivery.** Profiles move over SSH or a one-time token
   HTTPS server; never a web root.
5. **Fail loudly and safely.** Conflicts and missing dependencies produce a
   human-readable explanation and a fix command; nothing is deleted silently.

## Components

| Module | Responsibility |
|---|---|
| `steps/packages.py` | Install only required packages |
| `steps/haproxy.py` + `utils/haproxy.py` | Append-only HAProxy integration |
| `steps/pki.py` | Easy-RSA CA, server/client certs, CRL, tls-crypt key |
| `steps/pam.py` | Non-login accounts for password auth |
| `steps/openvpn.py` | Render server config, hardening, restart + rollback |
| `steps/kernel_fw.py` + `utils/firewall.py` | Idempotent firewall/NAT/sysctl |
| `steps/services.py` | Start and verify only what is used |
| `management/profile_gen.py` | Validated client profile rendering |
| `steps/client_profile.py` | Write profiles + root-only credentials sheet |
| `steps/user_db.py` | SQLite metadata and PBKDF2 hashes |
| `core/plan.py` | Dry-run rendering with a throwaway PKI |
| `validation/` | Post-install checks and `doctor` diagnostics |

## State and backups

* State: `/var/lib/vpn-installer/state.json` (mode 600), atomic writes.
* Backups: `/var/backups/vpn-installer/` (HAProxy and OpenVPN configs).
* Logs: `/var/log/vpn-installer/install.log` (rotated, redacted).
* PKI: `/etc/openvpn/pki/` (private dir mode 700).
* Profiles: `/etc/openvpn/clients/` (mode 700, files 600).
