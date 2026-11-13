# Changelog

All notable changes to this project are documented here.

## [2.0.0] - 2026-11-13

### Added
- Explicit wizard questions for server IP, domain-or-IP endpoint, public port,
  TCP/UDP, certificate+password or certificate-only auth, free or locked
  access, profile prefix, and number of unique users.
- Multi-user install: 1–50 profiles, each with a unique ECDSA P-384
  certificate, key, username and (in password mode) generated password.
- `vpn-installer plan`: complete dry-run renderer that creates a throwaway PKI
  and writes `server.conf`, all client profiles and the HAProxy block without
  touching the system.
- `vpn-installer doctor`: configuration-aware diagnostics with exact fixes.
- `vpn-installer download`: list profiles, print the SCP command, print a
  profile, or start a one-time tokenized HTTPS download server.
- Local download helpers: `scripts/download-ovpn.sh` (Linux/macOS/WSL) and
  `scripts/download-ovpn.ps1` (Windows).
- Optional VLESS/Reality multiplexing, now disabled by default and guarded
  against deleting non-VPN 3X-UI inbounds.
- Automatic Let's Encrypt acquisition for the optional VLESS TLS listener,
  with a self-signed fallback and a renewal deploy hook.
- Systemd hardening drop-in for OpenVPN that keeps `/var/log/openvpn`
  writable.
- Comprehensive tests for config validation, profile rendering, certificate /
  key matching, locked/free and TCP/UDP modes, HAProxy merge idempotency,
  conflict detection, and real `openvpn --config ... --show-gateway` parsing.

### Changed
- HAProxy is now integrated by appending one marked block to the existing
  config. Existing sections are preserved byte-for-byte; a timestamped backup
  is created; `haproxy -c` is run before reload; failures restore the backup.
- OpenVPN server config is generated from a Jinja2 template (single source of
  truth) instead of hardcoded strings in three places.
- Client profiles are generated from one validated template, pin the server
  certificate with `verify-x509-name server name`, and use `tls-crypt` for
  broad OpenVPN Connect compatibility.
- Server config uses AEAD data ciphers, `auth SHA256`, TLS 1.2 minimum (TLS
  1.3 negotiated), `dh none` with ECDSA, a real CRL, and no compression.
- New installs use `/etc/openvpn/clients/` (mode 700) instead of a world-
  readable web directory.
- Password hashing uses PBKDF2-HMAC-SHA256 (600k iterations) because Python
  3.13 removed the stdlib `crypt` module.
- Logging now writes a rotated `/var/log/vpn-installer/install.log` with
  credential redaction.
- State files are written atomically with mode 600; passwords are cleared from
  the persisted state after a successful install.
- `install.sh` is now a safe bootstrap that installs the Python wizard and
  hands off; it contains no credentials and no direct system configuration.
- `openvpn-wizard-linux.sh` and `openvpn-wizard-termux.sh` no longer contain
  hardcoded credentials and use SCP + OpenVPN Connect import.

### Fixed
- HAProxy port conflicts are detected before any change and reported with the
  exact line/process. The old installer silently replaced the whole file.
- Empty/invalid `crl.pem` files are no longer created; `easyrsa gen-crl` output
  is validated before use.
- Client profiles no longer include OpenSSL’s textual certificate dump before
  the PEM block.
- Certificate/key mismatches are detected while generating a profile, not at
  connection time.
- The installer no longer disables IPv6 system-wide or resets UFW/iptables.
- Locked mode no longer pushes `redirect-gateway` or DNS, and adds no NAT.
- Client profile rendering no longer depends on mutable attributes of a step
  class shared with the management module.
- `easyrsa` is invoked with an explicit `EASYRSA_VARS_FILE` and batch mode, so
  EC P-384 settings are actually applied on Debian/Ubuntu.
- The Python package now ships its Jinja2 templates (`templates/*.j2`).
- Release workflow builds the package from the repository root (the old
  workflow referenced a non-existent `installer/` directory).

### Security
- Private keys and profiles are never served over HTTP. The only network
  delivery options are SSH/SCP and an explicit one-time HTTPS token server.
- Credentials are passed to `chpasswd` over stdin, never argv.
- The SQLite database stores only PBKDF2 hashes, metadata and certificate
  serials — never private keys or plaintext passwords.
- The wizard refuses to touch a port already owned by another frontend or
  process; it never kills unrelated services.
- Systemd hardening is applied through a conservative drop-in.

### Removed
- The plain-HTTP nginx profile download site.
- Hardcoded server IP, username and password in the bash installers.
- System-wide IPv6 disabling.
- TLS-1.3-only profiles that break older OpenVPN Connect builds.

### Upgrade notes
- v1 `tls-crypt-v2` profiles are not compatible with the new `tls-crypt`
  server. Re-download profiles after upgrading.
- A healthy existing PKI is reused; an unusable one is moved aside, never
  deleted.
- The old HAProxy file is backed up before migration; see
  `docs/UPGRADING.md`.

---

## [1.1.0] - 2026-10-29

### Added
- Initial bash installer with OpenVPN over TCP/443 through HAProxy.
- Management scripts and QR code generation.

### Fixed
- Miscellaneous installer bugs and missing package handling.

---

## [1.0.0] - 2026-10-23

### Added
- Complete OpenVPN-over-HAProxy installer with interactive TUI.
- SNI routing for VLESS-TLS and VLESS-Reality.
- Easy-RSA PKI, PAM authentication, SQLite user management.
- Privacy education screens, progress UI, rollback support.
- Client profile generation with embedded certificates.

[2.0.0]: https://github.com/jackh0006/OpenVPN-Wizard/compare/v1.1.0...v2.0.0
