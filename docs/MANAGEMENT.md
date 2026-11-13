# User management (v2)

```bash
sudo vpn-installer manage
```

Menu:

| Option | Action | Certificate impact |
|---|---|---|
| 1 | Add user | Issues a new unique certificate/key |
| 2 | Revoke/remove | Revokes the cert, regenerates the CRL, reloads OpenVPN |
| 3 | Change password | PAM + PBKDF2 hash only |
| 4 | Rename profile | Renames the `.ovpn`; cert unchanged |
| 5 | Regenerate/export | Re-renders and validates the same profile |
| 6 | Detailed list | DB metadata, cert serial, status |
| 7 | Rotate certificate/key | Revokes old cert, issues a new key pair |
| 8 | Download command | Prints SCP and one-time HTTPS commands |
| 9 | Refresh | Reload the list |

## Add a user

The wizard asks for a profile name and username. In password mode it offers an
auto-generated strong password or a manual one. On success it prints:

* the profile path (`/etc/openvpn/clients/<name>.ovpn`)
* the password (once)
* the exact SCP download command

The new user can connect immediately; no service restart is required for a
new client certificate.

## Revoke a user

Revocation:

1. runs `easyrsa revoke <cert>`,
2. regenerates `crl.pem` and copies it to `/etc/openvpn/crl.pem`,
3. reloads OpenVPN,
4. deletes the profile,
5. marks the DB row revoked.

The next TLS renegotiation/connection for that certificate is rejected.
Existing long-lived sessions may continue until they reconnect.

## Change password

Updates the PAM account with `chpasswd` (stdin, never argv) and stores a new
PBKDF2 hash. Certificate-only installs do not show this option.

## Rotate keys

Use this when a profile leaks or a device is replaced. The old certificate is
revoked and a fresh one issued under a new CN; the profile is regenerated at
the same display name, so the user just re-imports it.

## Where things live

| Item | Path |
|---|---|
| Profiles | `/etc/openvpn/clients/` |
| PKI | `/etc/openvpn/pki/` |
| User DB | `/etc/openvpn/users.db` |
| Credentials sheet | `/root/openvpn-wizard-credentials.txt` |
| Installer state | `/var/lib/vpn-installer/state.json` |

The database stores `name`, `username`, PBKDF2 hash, certificate name/serial,
auth mode, access mode and profile path. It never stores private keys or
plaintext passwords.
