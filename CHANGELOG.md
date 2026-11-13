# Changelog

All notable changes to this project are documented here.

## [2.1.0] - 2026-11-13

### Added
- Live-setup detection: an existing `/etc/openvpn/server.conf` is read and its
  port, ciphers, TLS version, auth digest, MTU/MSS, socket buffers,
  verification mode, duplicate-CN policy and certificate CN are preserved.
- Smart HAProxy integration for a multi-service frontend: when an existing TCP
  frontend already binds the chosen port, the installer reuses a compatible
  VPN backend, or inserts one marked non-TLS `use_backend` rule and backend.
  It no longer needs to refuse just because port 443 is already used by a
  frontend that can be extended safely.
- IPv6 choice: disable it (default, matching the reference VPS) or keep it
  enabled with `--enable-ipv6`.
- Advanced tuning flags: `--tun-mtu`, `--mssfix`, `--sndbuf`, `--rcvbuf`,
  `--auth-digest`, `--tls-min`, `--tls-max`, `--internal-port`,
  `--verify-client-cert`, `--duplicate-cn`, `--no-detect`.
- Standard community files: governance, roadmap, authors, donations,
  pre-commit, Makefile, dev requirements, CodeQL and dependency review.
- Crypto donation addresses from the author's other repositories
  (`DONATIONS.md` and `.github/FUNDING.yml`).

### Changed
- Defaults now match the tested reference VPS: TLS 1.3, auth SHA384, MTU 1400,
  MSS 1360, send/receive buffers 524288, `tls-crypt`, `register-dns`.
- Existing PKI discovery now also checks `/root/easy-rsa/pki` and adopts an
  existing `ta.key` so old profiles keep working.
- Existing server certificate CNs (including `CN=ChangeMe`) are preserved and
  used in new profiles instead of forcing `CN=server`.
- HAProxy route insertion uses graceful reload where possible; services that
  are already active are not needlessly restarted.
- `PKIStep` always re-checks the existing PKI so RSA vs ECDSA and DH settings
  are correct on every run.

### Security
- IPv6 is disabled only as an explicit choice; enabling it is supported.
- Certificate-only mode still forces `verify-client-cert require`.
- No existing HAProxy section, route, certificate or unrelated firewall rule is
  deleted or rewritten.

### Fixed
- Easy-RSA no longer receives a conflicting global `EASYRSA_REQ_CN` for client
  or server certificate issuance (verified against Easy-RSA 3.1.7).
- A real CRL is generated instead of accepting an empty placeholder.
- The `tls-cipher` list stays under OpenVPN's 256-character option limit.
- OpenVPN is validated against the exact live `server.conf` shape (port 11944,
  RSA CN=ChangeMe, `verify-client-cert none`, `duplicate-cn`).

[2.1.0]: https://github.com/jackh0006/OpenVPN-Wizard/compare/v2.0.0...v2.1.0

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
