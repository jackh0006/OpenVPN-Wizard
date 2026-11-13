# Troubleshooting

Start with the built-in checks:

```bash
sudo vpn-installer doctor
sudo vpn-installer validate
```

The full log is at `/var/log/vpn-installer/install.log` (mode 600, rotated).

---

## The installer refuses to continue: port already in use

It prints the line number and the owning process. Nothing was changed.

```bash
sudo ss -ltnp | grep ':443'
```

Options:

1. Choose another port: `sudo vpn-installer install --port 8443`.
2. Free the port yourself (stop the unrelated service) and re-run.
3. Use UDP, which does not use HAProxy: `--proto udp`.

The installer never kills another service.

---

## HAProxy test fails

```bash
sudo haproxy -c -f /etc/haproxy/haproxy.cfg
sudo journalctl -u haproxy -n 100 --no-pager
```

A timestamped copy of the previous config is in
`/var/backups/vpn-installer/`. The installer restores it automatically when
its own change fails validation, so a broken pre-existing config stays your
responsibility to fix.

Remove only the VPN block with:

```bash
sudo vpn-installer uninstall
```

---

## OpenVPN does not start

```bash
sudo systemctl status openvpn@server --no-pager -l
sudo journalctl -u openvpn@server -n 100 --no-pager
```

Common causes:

| Log message | Fix |
|---|---|
| `Cannot open TUN/TAP dev` | The VPS kernel must provide `/dev/net/tun`. Ask the provider to enable TUN/TAP. |
| `error loading certificate` / `key mismatch` | `sudo vpn-installer manage` → rotate/export the affected profile. |
| `CRL: cannot open` | Re-run the installer; the CRL is regenerated in the PKI step. |
| `Address already in use` | Another process owns the port. `sudo ss -ltnp`. |
| `AUTH_FAILED` | The password is wrong or the PAM account is missing. `sudo vpn-installer manage` → change password. |
| `TLS Error: TLS key negotiation failed` | Usually a wrong profile/server mismatch or a network middlebox. Verify the endpoint and port. |

The installer keeps a timestamped backup at
`/var/backups/vpn-installer/openvpn-server.conf.<time>` and restores it if the
new config fails to start.

---

## Connected, but no internet (free mode)

```bash
# On the VPS
sysctl net.ipv4.ip_forward
sudo iptables -t nat -S POSTROUTING | grep MASQUERADE
sudo iptables -S FORWARD | grep tun0
```

The public interface detection can be checked with:

```bash
ip route show default
```

If the interface is not the one used in the NAT rule, re-run the installer
with the correct interface auto-detected, or re-run the firewall step. Do not
flush existing rules.

On the client, check the profile is **free**, not **locked**:

```bash
grep -E 'route-nopull|redirect-gateway' PROFILE.ovpn
```

---

## Locked mode still reaches the internet

Locked profiles contain:

```
route-nopull
route 10.8.0.0 255.255.255.0
pull-filter ignore "redirect-gateway"
pull-filter ignore "dhcp-option"
```

If those lines are missing, the profile is from a free-mode install. Re-export
the profile after changing the access mode.

---

## DNS leaks (free mode)

Free profiles push `9.9.9.9` and `149.112.112.112`. On Android, OpenVPN
Connect applies pushed DNS. On desktop Linux with `systemd-resolved`, verify:

```bash
resolvectl status tun0
```

If your client ignores pushed DNS, configure DNS manually or use a client
that honors `dhcp-option`.

---

## IPv6 leaks

v2 does **not** disable IPv6 on the host. Free profiles push `block-ipv6`; if
your client ignores it, disable IPv6 on that device or use a profile with
`--access locked` and route only what you need.

---

## Cannot download the profile

```bash
sudo ls -l /etc/openvpn/clients/
sudo vpn-installer download
```

From your device:

```bash
scp root@SERVER:/etc/openvpn/clients/NAME.ovpn ~/Downloads/
```

If SSH is not available, use the one-time HTTPS server:

```bash
sudo vpn-installer download NAME --serve
```

If the one-time server cannot bind, choose another port with `--port`.

---

## Certificate revoked, but the user still connects

The CRL is copied to `/etc/openvpn/crl.pem` and OpenVPN is reloaded. Check:

```bash
openssl crl -in /etc/openvpn/crl.pem -noout -text | head
sudo systemctl reload-or-restart openvpn@server
```

Existing sessions may survive until they reconnect; the next TLS
renegotiation rejects the revoked certificate.

---

## Lost the credentials file

It is at `/root/openvpn-wizard-credentials.txt` (mode 600). The database stores
only hashes, so a lost password cannot be recovered — set a new one:

```bash
sudo vpn-installer manage   # Change password
```

---

## Upgrade problems

See `docs/UPGRADING.md`. In short: keep backups, run `vpn-installer plan`
first, then install. The old HAProxy file is backed up before any migration.

---

## Collecting a bug report

```bash
sudo vpn-installer doctor > /tmp/doctor.txt 2>&1
sudo journalctl -u openvpn@server -n 200 --no-pager > /tmp/openvpn.txt
sudo journalctl -u haproxy -n 200 --no-pager > /tmp/haproxy.txt
```

Redact public IPs and any profile contents before posting publicly.
