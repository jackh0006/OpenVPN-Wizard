# Android / Termux

Termux cannot create a tun device without root. The correct Android flow is:

1. Download the `.ovpn` on the phone.
2. Hand it to **OpenVPN Connect**.
3. Connect from the app.

## Download with Termux

```bash
pkg install openssh
scp root@YOUR_SERVER:/etc/openvpn/clients/MHH06-01.ovpn ~/storage/downloads/
termux-open ~/storage/downloads/MHH06-01.ovpn
```

`termux-open` opens OpenVPN Connect with the profile ready to import.

Or use the included helper:

```bash
./openvpn-wizard-termux.sh --server root@YOUR_SERVER --profile MHH06-01
```

## No SSH client?

On the VPS:

```bash
sudo vpn-installer download MHH06-01 --serve
```

Open the printed one-time HTTPS URL in the phone browser, accept the
self-signed certificate, and import the downloaded file.

## Import into OpenVPN Connect

1. Open OpenVPN Connect → **Import** → **File**.
2. Select the downloaded `.ovpn`.
3. If the profile is password mode, enter the username/password from
   `/root/openvpn-wizard-credentials.txt` on the VPS.
4. Save and connect.

## Test

* Turn off Wi-Fi and use mobile data.
* Connect, then open `https://api.ipify.org` in the browser. It should show
  the VPS IP for free profiles.
* For locked profiles, the internet stays direct; only the VPN subnet is
  reachable.

## Battery and always-on

Android may suspend the VPN when the screen is off. In OpenVPN Connect,
enable the persistent/always-on notification if your version offers it. Do not
disable battery optimization for apps you do not trust.
