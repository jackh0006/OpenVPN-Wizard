# Start here — the simple guide

This guide assumes you have never set up a VPN before.

## 1. What you need

- A small Linux server (VPS) with Ubuntu 22.04 or 24.04.
- Its public IPv4 address. Example: `203.0.113.10`.
- About 10 minutes.
- Optional: a domain name such as `vpn.example.com`. You do **not** need one
  to start.

You will connect to the server with SSH. Your provider gives you a command
like:

```bash
ssh root@203.0.113.10
```

## 2. Install it

Copy and paste this into the server:

```bash
curl -fsSL https://raw.githubusercontent.com/jackh0006/OpenVPN-Wizard/main/install.sh | sudo bash
```

The script installs the tool and starts a question-and-answer wizard. It does
not change anything until you reach the confirmation screen. Press `Ctrl+C` at
any time before that and nothing happens.

You can also try it without changing anything:

```bash
vpn-installer plan --output ./vpn-plan
```

That writes example files into `./vpn-plan` only.

## 3. Answer the questions

| Question | What it means | Good first choice |
|---|---|---|
| Server IP | The address of this server | Confirm the detected address |
| Domain or IP | How phones will find the server | IP is fine; a domain is nicer later |
| Port | The door number clients use | `443` |
| TCP or UDP | Two ways to carry traffic | `tcp` if unsure; `udp` is often faster |
| Authentication | How users prove who they are | certificate + password |
| Access | What the VPN is allowed to do | free (full internet through the VPN) |
| IPv6 | A second, newer internet address family | disable (recommended, prevents leaks) |
| Profile prefix | Start of the file names | your name, e.g. `MHH06` |
| How many users | One file and one key per person | 3 is a good start |
| HAProxy | Shares port 443 with other TLS services | yes, it is safe and additive |

If the installer finds an existing OpenVPN server, it reuses its port, ciphers,
TLS version, MTU and socket buffers automatically. It does not replace a
working setup.

## 4. What the installer changes

- Adds or updates the OpenVPN configuration.
- Creates one folder of `.ovpn` files: `/etc/openvpn/clients/`.
- Writes a root-only credentials file:
  `/root/openvpn-wizard-credentials.txt`.
- Adds only one marked block or route to HAProxy, after making a backup.
- Adds only the firewall rules it needs.
- Never resets the firewall, never wipes HAProxy, and never deletes unrelated
  files.

If a service fails to start, the installer restores the previous config.

## 5. Download your profile

A `.ovpn` file is a small “key + address book” for the VPN app. Keep it private:
anyone who has it may be able to connect as you.

### Linux or macOS

```bash
scp root@YOUR_SERVER:/etc/openvpn/clients/MHH06-01.ovpn ~/Downloads/
```

### Windows (PowerShell)

```powershell
scp root@YOUR_SERVER:/etc/openvpn/clients/MHH06-01.ovpn $env:USERPROFILE\Downloads\
```

### Android

Install **OpenVPN Connect** from the Play Store. Then either:

- use an SSH/SFTP app to copy the file into `Downloads`, or
- on the server run:

```bash
sudo vpn-installer download MHH06-01 --serve
```

Open the printed one-time HTTPS link in the phone browser, accept the
self-signed certificate once, and the file downloads. The link works once and
the server stops by itself.

## 6. Connect

1. Open **OpenVPN Connect** (Android/iOS) or **OpenVPN GUI** (Windows) or
   **Tunnelblick** (macOS).
2. Choose **Import** → **File** and pick the `.ovpn`.
3. If the profile asks for a username and password, use the values in
   `/root/openvpn-wizard-credentials.txt`.
4. Press **Connect**.

## 7. Check it works

- Turn off Wi-Fi on the phone and use mobile data.
- Connect the VPN.
- Visit `https://api.ipify.org`. It should show the server’s IP.
- For a **locked** profile, the internet stays direct on purpose; only the
  private VPN network is reachable.

## 8. Add or remove people

```bash
sudo vpn-installer manage
```

- **Add user** creates a new certificate, key and profile. Nobody else changes.
- **Revoke/remove** blocks that one certificate immediately.
- **Rotate keys** is for a lost or leaked profile.
- **Download command** prints the exact `scp` line.

## 9. If something goes wrong

```bash
sudo vpn-installer doctor
sudo vpn-installer validate
```

`doctor` explains what is wrong and gives the exact command to fix it. The full
log is `/var/log/vpn-installer/install.log`.

If you changed something and want to go back:

```bash
sudo vpn-installer uninstall
```

That stops the VPN, removes only this installer’s HAProxy block and firewall
rules, and leaves your certificates and unrelated services alone. Add
`--purge` only if you also want to delete the keys and profiles.

## 10. Words explained

| Word | Plain meaning |
|---|---|
| VPS | A rented computer in a data centre |
| IP address | The computer’s phone number on the internet |
| Port | A numbered door on that computer (`443` is the HTTPS door) |
| TCP / UDP | Two delivery styles; TCP is more compatible, UDP is often faster |
| DNS | The internet’s contact list (names → IP addresses) |
| Certificate | A tamper-proof ID card for the server or a user |
| Private key | The secret half of that ID card; never share it |
| `.ovpn` | The file you import into the VPN app |
| MTU / MSS | How big each network packet is allowed to be |
| IPv6 | A newer address system; disabling it prevents some leaks |
| HAProxy | A traffic director that can share one port between services |

## 11. Honest limits

- A VPN hides your traffic from your local network and ISP, but the VPS
  provider can still see that a connection exists and terminates it.
- TCP/443 looks like HTTPS at the port level. A determined blocking system can
  still identify OpenVPN. The optional VLESS/Reality mode is harder to detect.
- No setup can protect a device that is already compromised.
- Keep the `.ovpn` and the credentials file private. Revoke and rotate if one
  leaks.
