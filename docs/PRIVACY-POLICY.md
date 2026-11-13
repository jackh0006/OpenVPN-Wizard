# OpenVPN Wizard - Privacy Policy

## What We Collect

**Nothing.** Zero. Nada.

We do not collect:
- Your IP address
- Your browsing history
- Your DNS queries
- Your personal information
- Any usage statistics
- Any telemetry data

## What We Send

**Nothing.** The installer connects only to:

1. **Package repositories (apt)** — to install the required software
2. **A public IP echo service** — once, to pre-fill the server IP (you confirm it)
3. **Let's Encrypt** — only if you explicitly enable the optional VLESS listener
   with a domain; certificate validation is the only reason

There is no telemetry, analytics, update check or phone-home code.

## What We Store

Everything stays on your VPS. Nothing is sent to us or any third party:

| Location | What's Stored |
|----------|--------------|
| `/etc/openvpn/` | Server configuration, runtime certs, CRL |
| `/etc/openvpn/pki/` | Certificate Authority, server/client certificates |
| `/etc/openvpn/clients/` | Client .ovpn profiles (mode 600) |
| `/etc/openvpn/users.db` | User metadata and PBKDF2 hashes |
| `/root/openvpn-wizard-credentials.txt` | One-time credentials sheet (mode 600) |
| `/var/log/vpn-installer/` | Rotated installer log, redacted |
| `/etc/haproxy/` | One marked VPN block inside your config |
| `/etc/x-ui/` | Optional 3X-UI configuration |

## Third-Party Services

**None.** We do not use:
- Analytics services
- Crash reporting
- Update checking
- Telemetry
- Advertising
- Tracking pixels

## Data Access

Only you (the VPS owner) have access to:
- Your VPN configuration
- Your user database
- Your certificates and keys
- Your traffic logs (if you enable them)

We (jackh0006) never have access to your data, your server, or your traffic.

## Your Rights

You have the right to:
- Inspect all source code (it's open source)
- Modify the software for your needs
- Uninstall at any time
- Delete all data by removing the software
- Export your user data at any time

## Contact

Privacy questions: jackh109867@gmail.com