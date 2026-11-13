# Installation guide (v2)

## Requirements

| Item | Requirement |
|---|---|
| OS | Ubuntu 22.04/24.04 or Debian 12 |
| Architecture | x86_64 or arm64 |
| RAM | 512 MB minimum, 1 GB recommended |
| Disk | 2 GB free |
| Network | Public IPv4 address |
| DNS | Optional domain pointing at the VPS |
| Access | root / sudo |

You do **not** need three domains. VLESS/Reality is optional and off by
default.

## Recommended install

```bash
curl -fsSL https://raw.githubusercontent.com/jackh0006/OpenVPN-Wizard/main/install.sh | sudo bash
```

The bootstrap installs Python, clones the source to `/opt/openvpn-wizard-src`,
creates `/opt/vpn-installer`, and starts the interactive wizard.

## From a clone

```bash
git clone https://github.com/jackh0006/OpenVPN-Wizard.git
cd OpenVPN-Wizard
sudo bash install.sh
```

## Safe dry run first

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
vpn-installer plan --output ./vpn-plan --profiles 3
```

This renders real certificate/key files and every config into `./vpn-plan/`
without changing the system. Inspect them, then run the real installer.

## Questions you will be asked

1. **Server public IP** — auto-detected, confirm or replace.
2. **Domain or IP endpoint** — how clients address the server.
3. **Public port** — default 443.
4. **TCP or UDP** — TCP can share 443 via HAProxy; UDP binds directly.
5. **Authentication** — certificate + password, or certificate only.
6. **Access** — free (full tunnel) or locked (VPN network only).
7. **Profile prefix** — used in `.ovpn` file names.
8. **How many profiles** — 1 to 50, each with a unique key.
9. **HAProxy** — attach the VPN to the existing config (TCP only).
10. **VLESS** — optional advanced multiplexing on the same 443 listener.

## Ports

| Port | Protocol | When |
|---|---|---|
| 22 | TCP | SSH management |
| 443 | TCP | Default VPN/HAProxy listener |
| 443 | UDP | Default when UDP is chosen |
| 10000, 10004 | TCP | Loopback only, optional VLESS |
| 80 | TCP | Only during optional Let's Encrypt HTTP-01 |

The installer opens the VPN port. It never resets or flushes the firewall.

## After install

```bash
sudo vpn-installer validate
sudo vpn-installer doctor
```

Download the profiles (see `docs/DOWNLOAD.md`) and import them into OpenVPN
Connect, OpenVPN GUI or Tunnelblick.

## Uninstall

```bash
sudo vpn-installer uninstall          # stop + detach, keep keys/profiles
sudo vpn-installer uninstall --purge  # also delete installer-owned keys/data
```

Packages and unrelated HAProxy/iptables rules are left alone.
