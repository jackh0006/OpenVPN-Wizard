# OpenVPN Wizard v2.1

Hardened, **non-destructive** OpenVPN deployment for Ubuntu/Debian VPS.

It asks exactly what it needs — server IP, domain or IP, TCP or UDP, port,
certificate+password or certificate-only, locked or free access, profile names
and how many users — then builds one unique `.ovpn` per user and applies only
the changes it owns.

[![CI](https://github.com/jackh0006/OpenVPN-Wizard/actions/workflows/ci.yml/badge.svg)](https://github.com/jackh0006/OpenVPN-Wizard/actions/workflows/ci.yml)
**New to VPNs?** Start with the plain-English [Beginner Guide](docs/BEGINNER-GUIDE.md). It explains every question and every command without assuming prior knowledge.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Ubuntu 22.04+](https://img.shields.io/badge/Ubuntu-22.04%2B-orange.svg)](https://ubuntu.com/)

---

## Quick start

```bash
curl -fsSL https://raw.githubusercontent.com/jackh0006/OpenVPN-Wizard/main/install.sh | sudo bash
```

or from a clone:

```bash
git clone https://github.com/jackh0006/OpenVPN-Wizard.git
cd OpenVPN-Wizard
sudo bash install.sh
```

You can inspect everything first, without root or system changes:

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e .
vpn-installer plan --output ./vpn-plan --profiles 3
```

That writes a complete `server.conf`, one client profile per user, and the
exact HAProxy block into `./vpn-plan/`. It creates a throwaway PKI for the
plan only. `vpn-installer plan` is the safe way to check the result before
deploying.

---

## What the wizard asks

| Question | Choices | Notes |
|---|---|---|
| Server public IP | IPv4 | Auto-detected, always confirmed |
| Clients connect via | domain **or** IP | Domain is recommended if you want TLS/Reality later |
| Public port | 1–65535 | 443 blends in with HTTPS |
| Transport | **TCP** or **UDP** | TCP can share 443 via HAProxy; UDP binds directly |
| Authentication | **certificate + password** or **certificate only** | Every user always gets a unique key |
| Access | **free** (full tunnel) or **locked** (VPN network only) | Locked adds no NAT/exit-node risk |
| IPv6 | **disable** (recommended) or **keep enabled** | Disabling prevents IPv6 leaks; it does not affect IPv4 |
| Profile prefix | e.g. `MHH06` | Used for the `.ovpn` filenames |
| Number of profiles | 1–50 | Each gets a separate cert, key and password |

Advanced users can also set `--tun-mtu`, `--mssfix`, `--sndbuf`, `--rcvbuf`,
`--auth-digest`, `--tls-min`, `--tls-max`, `--internal-port`,
`--verify-client-cert` and `--duplicate-cn`. The defaults match the tested
reference VPS: MTU 1400, MSS 1360, 512 KiB socket buffers, SHA384, TLS 1.3.

It also asks whether to attach the VPN to HAProxy (TCP only) and offers the
optional VLESS/Reality multiplexing path.

### Non-interactive example

```bash
sudo vpn-installer install --non-interactive \
  --server-ip 203.0.113.10 \
  --domain vpn.example.com \
  --port 443 --proto tcp \
  --auth userpass --access free \
  --prefix MHH06 --profiles 3
```

Profiles are named `MHH06-01`, `MHH06-02`, `MHH06-03`, with unique usernames,
certificates and generated passwords. Passwords are printed in the wizard and
written to `/root/openvpn-wizard-credentials.txt` (mode 600).

Other useful invocations:

```bash
# UDP, certificate-only, private-network-only
sudo vpn-installer install -n --server-ip 203.0.113.10 --proto udp \
  --auth cert --access locked --profiles 2

# Bind directly to 443 without HAProxy
sudo vpn-installer install -n --server-ip 203.0.113.10 --no-haproxy

# Custom profile names
sudo vpn-installer install -n --server-ip 203.0.113.10 \
  --users MHH06-Phone,MHH06-Laptop,Tablet
```

Run `vpn-installer install --help` for the complete option list.

---

## What gets installed

| Component | Purpose | Public listener? |
|---|---|---|
| OpenVPN | Encrypted tunnel, AEAD ciphers, `tls-crypt`, per-user certificates, CRL | Only behind HAProxy or when UDP/direct |
| HAProxy | Optional TCP port sharing (OpenVPN + TLS SNI routing) | Yes, if enabled |
| Easy-RSA | ECDSA P-384 CA, server cert, unique client certs, CRL | No |
| iptables/UFW | Only the specific allow/NAT rules required | — |
| 3X-UI | Optional VLESS/Reality multiplexing (advanced) | Loopback only |
| SQLite | User metadata and PBKDF2 password hashes | No |

### Cryptographic profile (client and server)

```
Data channel:  AES-256-GCM, CHACHA20-POLY1305, AES-128-GCM (AEAD)
Control:       TLS 1.3 (1.2 available with --tls-min 1.2)
Control auth:  tls-crypt v1 (hides and authenticates the control channel)
Certificates:  ECDSA P-384, unique per user
Server pinning: verify-x509-name server name + remote-cert-tls server
Compression:   disabled (avoids VORACLE-style compression oracles)
CRL:           checked on every connection; revoking a user takes effect immediately
```

The defaults (`TLS 1.3`, `SHA384`, MTU 1400, MSS 1360, 512 KiB buffers) match
the tested reference VPS. If you need older client compatibility, run with
`--tls-min 1.2`. `tls-crypt` (v1) is used instead of `tls-crypt-v2` because it
is supported by every current OpenVPN client, including OpenVPN Connect on
Android/iOS.

---

## Downloads (from the VPS to your device)

Profiles live in `/etc/openvpn/clients/` (directory 700, files 600). Nothing
is served over plain HTTP.

### Linux / macOS / WSL

```bash
scp root@YOUR_SERVER:/etc/openvpn/clients/MHH06-01.ovpn ~/Downloads/
```

Or use the helper on your local machine:

```bash
bash scripts/download-ovpn.sh root@YOUR_SERVER MHH06-01
```

### Windows (PowerShell)

```powershell
scp root@YOUR_SERVER:/etc/openvpn/clients/MHH06-01.ovpn $env:USERPROFILE\Downloads\
```

Or:

```powershell
.\scripts\download-ovpn.ps1 -Server root@YOUR_SERVER -Profile MHH06-01
```

### Android

Option A — Termux:

```bash
pkg install openssh
scp root@YOUR_SERVER:/etc/openvpn/clients/MHH06-01.ovpn ~/storage/downloads/
```

Then open the file with **OpenVPN Connect**.

Option B — one-time HTTPS link (no SSH client needed):

```bash
sudo vpn-installer download MHH06-01 --serve
```

This starts a short-lived HTTPS server with a 256-bit random token, serves
exactly one file once, and exits. The certificate is self-signed; accept it
once in the browser.

### Print through SSH

```bash
ssh root@YOUR_SERVER 'vpn-installer download MHH06-01 --print' > MHH06-01.ovpn
```

Import the resulting file into **OpenVPN Connect** (Android/iOS), **OpenVPN
GUI** (Windows) or **Tunnelblick** (macOS).

---

## Non-destructive HAProxy integration

This is the part most installers get wrong. v2 **never rewrites** your
`/etc/haproxy/haproxy.cfg`. Instead it:

1. checks whether another frontend already binds the requested port;
2. backs up the current file to `/var/backups/vpn-installer/`;
3. appends one clearly marked block:
   ```haproxy
   # >>> openvpn-wizard managed block (v2) - do not edit >>>
   frontend ovpn_wizard_frontend_443
       bind *:443
       ...
   backend ovpn_wizard_openvpn
       server openvpn 127.0.0.1:<internal-port>
   # <<< openvpn-wizard managed block <<<
   ```
4. runs `haproxy -c -f …` before reloading;
5. restores the previous file automatically if validation or reload fails.

On later runs it replaces **only** that block. `vpn-installer uninstall`
removes **only** that block. To detach the VPN manually, delete the marked
block and reload HAProxy.

If another service already owns the port, the installer refuses to proceed
and tells you exactly which line/process is responsible. It never kills or
reconfigures unrelated services. Use `--port 8443`, `--proto udp`, or free the
port yourself.

---

## Firewall and kernel changes

* Opens only the VPN public port (`tcp` or `udp`) and preserves existing rules.
* Adds NAT/forwarding **only in free mode**. Locked mode deliberately adds no
  NAT, so the VPS cannot be used as an internet exit node.
* Never runs `ufw reset` and never flushes iptables. IPv6 is disabled only when you choose that option.
* Writes `/etc/sysctl.d/99-openvpn-wizard.conf`; enables BBR only when the
  kernel module is actually available.
* Persists rules with `netfilter-persistent` when present, otherwise with
  `iptables-save` into the existing `/etc/iptables/rules.v4`.

---

## Management

```bash
sudo vpn-installer manage      # add, revoke, rename, rotate, export
sudo vpn-installer validate    # re-run all checks
sudo vpn-installer doctor      # explain problems and exact fixes
sudo vpn-installer download    # list profiles / show download options
sudo vpn-installer uninstall   # detach safely (keeps keys unless --purge)
```

Management actions:

| Action | Effect |
|---|---|
| Add user | New unique certificate/key + profile; old users untouched |
| Revoke user | Adds cert to CRL, reloads OpenVPN, deletes the profile |
| Change password | Updates PAM and the hash in SQLite |
| Rename profile | Renames the `.ovpn`; certificate is unchanged |
| Rotate keys | Revokes the old cert and issues a new key pair |
| Export | Re-renders and validates the profile |

The SQLite database stores PBKDF2 hashes and metadata only. It never stores
private keys or plaintext passwords.

---

## Live verification

v2.1 was checked read-only against a working Ubuntu 22.04 VPS running OpenVPN
on `127.0.0.1:11944` behind an existing HAProxy frontend on `*:443`. The
planner detected the existing `bk_ovpn` route and reported `action: reuse`; applying the manager to a copy of the live config returned the
same SHA-256, so HAProxy was untouched. A profile generated from the existing
PKI completed a TLS 1.3 handshake and certificate verification (`CN=ChangeMe`)
against the live server. Details: [docs/LIVE-VERIFICATION.md](docs/LIVE-VERIFICATION.md).

## Honest security notes

* Traffic between client and VPS is encrypted and authenticated with modern
  AEAD ciphers, `tls-crypt`, and unique ECDSA certificates.
* TCP/443 makes the connection look like HTTPS **at the port level**. A
  determined DPI system that blocks unknown protocols can still identify
  OpenVPN; no OpenVPN configuration can guarantee invisibility. The optional
  VLESS/Reality path is the stronger anti-DPI option.
* A VPS operator can always observe metadata (connection times, volume) and,
  because the VPN terminates there, traffic in principle. Use a provider you
  trust.
* TCP inside TCP can reduce throughput on lossy links. Use UDP if speed
  matters and the network allows it.
* IPv6 is **disabled by default** (matching the reference VPS) and clients are
  told to block it. Use `--enable-ipv6` if you need host IPv6; the tunnel itself
  is IPv4-only, so judge whether that is appropriate for your network.
* Treat `.ovpn` files as private keys. Use `scp`/the one-time token server,
  never email or chat. Revoke and rotate if one leaks.

---

## Requirements

* Ubuntu 22.04/24.04 or Debian 12 (x86_64 or arm64)
* Root access
* A public IPv4 address
* For domain mode: a DNS A/AAAA record pointing at the VPS
* Ports: the chosen VPN port (443 by default); port 80 only if you enable
  Let's Encrypt for the optional VLESS listener

---

## Upgrade from v1

v1 hardcoded credentials and replaced the entire HAProxy config. v2 does
neither. Before upgrading:

1. Keep a copy of the current profiles.
2. Run `sudo vpn-installer install` (v2). If it detects the exact v1 HAProxy
   layout, it backs it up and migrates to the append-only layout — the backup
   path is printed.
3. Existing PKI at `/etc/openvpn/pki`, `/etc/openvpn/easy-rsa/pki` or
   `/root/easy-rsa/pki` is reused when healthy, so current profiles keep
   working. The existing TLS-crypt key, certificate CN, port, ciphers, TLS
   version, MTU and socket buffers are detected and preserved automatically.
4. Re-download profiles for the new users. v1 tls-crypt-v2 clients are
   converted to standard `tls-crypt` only for newly generated profiles; do not
   delete the old `.ovpn` files until the new ones are tested.

If anything looks wrong, run `sudo vpn-installer doctor` and read the full log
at `/var/log/vpn-installer/install.log`.

---

## Development

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest -q
vpn-installer plan --output /tmp/vpn-plan
```

The test suite renders real certificates and profiles, checks certificate/key
matching, verifies HAProxy merge idempotency, and asks the real `openvpn`
binary to parse every generated configuration when it is installed.

---

## Donations

Optional crypto donations are welcome. The same public addresses are used in
the author's other repositories. Full details and network warnings:
**[DONATIONS.md](DONATIONS.md)**.

| Asset | Address |
|---|---|
| Bitcoin (BTC) | `bc1q8t0fn2yrsy4lh3m0pz34uj27t8vxjeavkjym83` |
| Ethereum / BNB / USDT-USDC EVM | `0xdad428900a4359be8f76b3062df34211582e09eb` |
| TRON / USDT TRC-20 | `TMpb6RNTuGNM1eTakm9kjds1mRTPYYJesf` |
| Solana / USDT-USDC SPL | `BDCCrRez1yD1RpkAtiqKKDk3BfxPD8P7nkL26jCYrzgL` |
| Litecoin (LTC) | `ltc1q2gs89cfy3mumr7gu9w0zl9rllf80q67m5rmma8` |

> Use the exact address from [DONATIONS.md](DONATIONS.md). Never send on the
> wrong network; crypto transfers are irreversible.

## License

MIT. Made by [jackh0006](https://github.com/jackh0006) ·
jackh109867@gmail.com. No telemetry, no tracking, no phone-home.
