# Downloading profiles safely

Every user gets a separate file:

```
/etc/openvpn/clients/<profile>.ovpn
```

The directory is mode `700`, every profile is mode `600`. The installer never
serves this directory over HTTP and never enables directory listing.

## Recommended: SSH/SCP

SSH already encrypts and authenticates the transfer and adds no new open port.

### Linux / macOS / WSL

```bash
scp root@SERVER:/etc/openvpn/clients/PROFILE.ovpn ~/Downloads/
```

### Windows 10/11 (PowerShell)

```powershell
scp root@SERVER:/etc/openvpn/clients/PROFILE.ovpn $env:USERPROFILE\Downloads\
```

Windows ships the OpenSSH client. If `scp` is missing, install the
“OpenSSH Client” optional feature.

### Android (Termux)

```bash
pkg install openssh
scp root@SERVER:/etc/openvpn/clients/PROFILE.ovpn ~/storage/downloads/
termux-open ~/storage/downloads/PROFILE.ovpn
```

`termux-open` hands the file to OpenVPN Connect. OpenVPN Connect performs the
actual VPN connection; Termux cannot create a tun device without root.

### iOS

Use an SFTP/SSH app (for example Secure ShellFish, Termius or Working Copy)
and save the file to the Files app, then open it with OpenVPN Connect.

## Local helper scripts

The repository includes:

```bash
scripts/download-ovpn.sh root@SERVER PROFILE
```

```powershell
scripts\download-ovpn.ps1 -Server root@SERVER -Profile PROFILE
```

Both verify the file contains the expected `<ca>` and `<key>` blocks before
keeping it. They refuse to overwrite an existing file.

## One-time HTTPS link (phones, no SSH client)

On the VPS:

```bash
sudo vpn-installer download PROFILE --serve
```

Output:

```
https://SERVER:8443/t/<256-bit-random-token>/PROFILE.ovpn
```

* The server is HTTPS only, TLS 1.2+ with a fresh self-signed certificate.
* Only the tokenized path is served; everything else returns 404.
* Exactly one successful download is allowed.
* It shuts down after the first download or after `--ttl` seconds (default 300).
* Nothing is left running afterwards.

You can change the port and lifetime:

```bash
sudo vpn-installer download PROFILE --serve --port 9443 --ttl 120
```

Open the printed URL on the device (accept the self-signed certificate once).
If the VPS firewall is active, allow the chosen port for the duration, for
example: `sudo ufw allow 8443/tcp` (remove it afterwards).
Then import the downloaded file into OpenVPN Connect.

## Printing through SSH

```bash
ssh root@SERVER 'vpn-installer download PROFILE --print' > PROFILE.ovpn
chmod 600 PROFILE.ovpn
```

## What not to do

* Do not email, chat or paste a `.ovpn` file. It contains a private key.
* Do not copy profiles into a web root or enable `autoindex`.
* Do not share one profile between people; the installer creates unique
  certificates for a reason.
* If a profile leaks: `vpn-installer manage` → **Revoke/remove user**, then
  add the user again (or rotate their keys).

## After downloading

1. Import the file into OpenVPN Connect / OpenVPN GUI / Tunnelblick.
2. Connect on mobile data (not the same network as the VPS) for a realistic
   test.
3. Confirm the exit IP is the VPS: `curl -s https://api.ipify.org`.
4. For free-tunnel profiles, confirm DNS works and no IPv6 leak remains.
5. For locked profiles, confirm only the VPN subnet is reachable — the local
   internet must remain direct.
