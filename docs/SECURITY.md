# Security model (v2)

This document describes what OpenVPN Wizard actually does, and what it does
not claim.

## Threat model

| Adversary | Capability | What v2 does |
|---|---|---|
| ISP / network DPI | Passive capture, protocol fingerprints, blocking | Encrypts and authenticates the tunnel; TCP/443 is indistinguishable at the port level; `tls-crypt` hides the control channel. Does **not** guarantee evasion of an active DPI system that blocks unknown protocols. |
| Local network | MITM, captive portals | Server certificate pinning (`verify-x509-name server name` + `remote-cert-tls server`) prevents silent MITM. |
| Stolen profile | Possession of one `.ovpn` | That one certificate can be revoked without touching other users; CRL is enforced on every connect. |
| VPS provider | Host-level access | Can observe metadata and terminate traffic. Choose a provider you trust. |
| Other VPN users | Same server | No `client-to-client`; each user is isolated unless you add it deliberately. |

## Cryptography

```
Control channel   TLS 1.3 by default (1.2 only with --tls-min 1.2)
                  TLS_AES_256_GCM_SHA384
                  TLS_CHACHA20_POLY1305_SHA256
                  TLS_AES_128_GCM_SHA256
                  tls-crypt v1 (authenticated, encrypted control channel)
Data channel      AES-256-GCM, CHACHA20-POLY1305, AES-128-GCM
                  data-ciphers-fallback AES-256-GCM
Tuning            MTU 1400, MSS 1360, buffers 524288, SHA384, TLS 1.3
Certificates      ECDSA P-384 for new PKIs; an existing RSA PKI is reused
CRL               regenerated on every revocation, enforced by OpenVPN
Compression       disabled (no comp-lzo / compress; avoids compression oracles)
```

### Why ECDSA P-384?

It is fast on low-power VPS instances, avoids slow DH parameter generation
(`dh none`), and is supported by every current OpenVPN client. A legacy RSA
PKI is detected and reused; in that case the installer generates and uses a
real `dh.pem`.

### Why `tls-crypt` and not `tls-crypt-v2`?

`tls-crypt` is supported by OpenVPN Connect on Android/iOS, OpenVPN GUI,
Tunnelblick and the openvpn CLI. `tls-crypt-v2` is stronger in some deployment
models but is not universally supported; choosing it would break the “works
on a normal phone” requirement. Profiles are single-user, so the v2 key
distribution advantage is not needed.

### Why TLS 1.3 by default?

The tested reference VPS uses TLS 1.3 only and its profiles work on Android
OpenVPN Connect. If you need an older client, run with `--tls-min 1.2`; the
generated profiles and server config will then allow TLS 1.2 as well.

## Authentication modes

### Certificate + password (recommended)

OpenVPN requires **both** a valid client certificate and a PAM password. The
certificate is unique per user; the PAM account has `/usr/sbin/nologin` and is
never usable for SSH. Revoking either the certificate or the account blocks
the user.

### Certificate only

OpenVPN requires a valid client certificate; no password prompt. Useful for
devices where typing a password is impractical. The profile is then a bearer
credential: treat it like a private key, and rotate it if lost.

## Access modes

* **Free** — pushes `redirect-gateway`, DNS servers and (unless IPv6 is
  explicitly enabled) `block-ipv6`; the VPS NATs client traffic. This makes the
  VPS the internet exit.
* **Locked** — no `redirect-gateway`, no DNS push, no NAT. The client uses
  `route-nopull`, a route only to the VPN subnet, and ignores pushed DNS. The
  VPS cannot be used as an exit node.

## File permissions

| Path | Mode | Notes |
|---|---|---|
| `/etc/openvpn/pki/private/` | 700 | CA and client private keys |
| `/etc/openvpn/pki/private/*.key` | 600 | |
| `/etc/openvpn/server.conf` | 600 | |
| `/etc/openvpn/clients/` | 700 | |
| `/etc/openvpn/clients/*.ovpn` | 600 | Contains a private key |
| `/root/openvpn-wizard-credentials.txt` | 600 | Delete after distribution |
| `/etc/openvpn/users.db` | 600 | PBKDF2 hashes only |
| `/var/log/vpn-installer/install.log` | 600 | Credentials are redacted |

## Logging and privacy

* The installer has no telemetry and makes no analytics calls.
* The only outbound calls are package downloads, optional public-IP detection,
  and (only if you explicitly enable VLESS with a domain) Let's Encrypt.
* Passwords are passed to `chpasswd` over stdin, never via argv or a shell
  string. Log lines matching password patterns are redacted.

## What v2 deliberately does not do

* It does not disable IPv6 unless you choose that option (the default is
  disabled, matching the reference VPS, because the tunnel is IPv4-only).
* It does not flush, reset or disable the firewall.
* It does not overwrite unrelated HAProxy sections.
* It does not serve profiles over HTTP.
* It does not claim to defeat every DPI system.
