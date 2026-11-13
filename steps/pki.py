"""
Step: bootstrap or reuse the Easy-RSA PKI.

The step is idempotent and non-destructive:
* a healthy existing PKI is reused and missing client certificates are added;
* a foreign/broken directory is moved aside with a timestamp, never deleted;
* generated keys use ECDSA P-384, so ``dh none`` is safe and startup is fast.
"""

from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path
from typing import Callable

from core.config import InstallConfig
from core.exceptions import PKIError
from steps.base import BaseStep


class PKIStep(BaseStep):
    @property
    def name(self) -> str:
        return "pki"

    @property
    def display_name(self) -> str:
        return "Create or reuse certificates"

    @property
    def description(self) -> str:
        return "Easy-RSA CA, server certificate, per-user client certificates, CRL and TLS-crypt key"

    async def is_already_done(self, config: InstallConfig) -> bool:
        # Always run: it is idempotent, reuses a healthy PKI, adds missing
        # user certificates, regenerates the CRL, and detects RSA vs ECDSA
        # so the correct DH setting is applied.
        return False

    async def execute(self, config: InstallConfig,
                      output_callback: Callable[[str], None] = None) -> bool:
        def log(msg: str):
            if output_callback:
                output_callback(msg)
            self.logger.info(msg)

        cert_names = [u.safe_cert_name for u in config.users]
        if len(cert_names) != len(set(cert_names)):
            raise PKIError(
                "Two users map to the same certificate name; each user must "
                "have a different key. Give every profile a different username."
            )

        config.pki_dir = str(self._select_pki_dir(config, log))
        pki = Path(config.pki_dir)
        easyrsa = self._find_easyrsa()

        if self._healthy(pki):
            log(f"Reusing existing PKI at {pki}")
            self._sanitize_vars(pki)
        else:
            self._prepare_clean_pki(pki, log)
            log("Initialising Easy-RSA PKI...")
            self._easyrsa(easyrsa, config, ["init-pki"])
            self._write_vars(config, pki)
            log("Building CA (ECDSA P-384, 10 year validity)...")
            self._easyrsa(easyrsa, config, ["--batch", "build-ca", "nopass"])

        # Server certificate (reuse it exactly, including its CN).
        server_crt = pki / "issued" / "server.crt"
        if not server_crt.exists():
            log("Issuing server certificate (CN=server)...")
            self._easyrsa(easyrsa, config, ["--batch", "build-server-full", "server", "nopass"])
            config.server_cert_cn = "server"
        else:
            cn = self._cert_cn(server_crt)
            if not cn:
                raise PKIError(
                    f"Could not read the server certificate CN from {server_crt}",
                    fix_hint="Check that the certificate is valid PEM.",
                )
            config.server_cert_cn = cn
            log(f"Reusing existing server certificate (CN={cn})")

        # RSA CAs (including a v1 PKI) need DH parameters; ECDSA does not.
        key_algo = self._run_cmd(
            ["openssl", "x509", "-in", str(server_crt), "-noout", "-text"],
            check=False,
        ).stdout
        if "Public Key Algorithm: rsaEncryption" in key_algo:
            config.dh = str(Path(config.openvpn_dir) / "dh.pem")
            log("RSA server certificate detected; DH parameters will be used")
        else:
            config.dh = "none"

        # One unique certificate + key per user.
        for user in config.users:
            cert_name = user.safe_cert_name
            crt = pki / "issued" / f"{cert_name}.crt"
            key = pki / "private" / f"{cert_name}.key"
            if crt.exists() and key.exists():
                log(f"Reusing certificate for {user.name} ({cert_name})")
            else:
                log(f"Issuing unique certificate for {user.name} ({cert_name})...")
                self._easyrsa(
                    easyrsa, config,
                    ["--batch", "build-client-full", cert_name, "nopass"],
                )
            if not crt.exists() or not key.exists():
                raise PKIError(
                    f"Easy-RSA did not create a certificate for {user.name}",
                    fix_hint=(
                        "Check 'journalctl -xe' and disk space, then re-run. "
                        "The PKI directory was not modified elsewhere."
                    ),
                )

        log("Generating certificate revocation list (CRL)...")
        self._easyrsa(easyrsa, config, ["gen-crl"])

        ta_key = pki / "ta.key"
        if not ta_key.exists():
            self._adopt_ta_key(pki)
        if not ta_key.exists():
            log("Generating TLS-crypt (v1) static key...")
            self._generate_ta_key(ta_key)
        else:
            log("Reusing existing TLS-crypt key")

        log("Copying runtime material into /etc/openvpn ...")
        self._copy_runtime_assets(config)

        log("Setting private-key permissions (600 / owner root)...")
        self._secure_permissions(pki, config)

        log("Verifying certificate chain...")
        self._verify(config, pki)

        log("PKI ready: CA, server, "
            f"{len(config.users)} client certificate(s), CRL and tls-crypt key")
        return True

    # ── Helpers ──────────────────────────────────────────────────────────

    def _select_pki_dir(self, config: InstallConfig, log) -> Path:
        """Prefer the configured location, then an existing v1 Django-style PKI."""
        candidates = [
            Path(config.pki_dir),
            Path("/etc/openvpn/easy-rsa/pki"),
            Path("/root/easy-rsa/pki"),
        ]
        for candidate in candidates:
            if (candidate / "ca.crt").exists() and (candidate / "private" / "ca.key").exists():
                if candidate != Path(config.pki_dir):
                    log(f"Found an existing PKI at {candidate}; reusing it instead of creating a new CA")
                return candidate
        return Path(config.pki_dir)

    def _healthy(self, pki: Path) -> bool:
        return (
            (pki / "ca.crt").exists()
            and (pki / "private" / "ca.key").exists()
            and (pki / "issued" / "server.crt").exists()
            and (pki / "private" / "server.key").exists()
        )

    def _prepare_clean_pki(self, pki: Path, log) -> None:
        if pki.exists() and any(pki.iterdir()):
            backup = pki.with_name(f"{pki.name}.bak-{int(time.time())}")
            log(f"Existing directory is not a usable PKI; moving it to {backup} (not deleted)")
            pki.rename(backup)
        pki.mkdir(parents=True, exist_ok=True)

    def _find_easyrsa(self) -> str:
        candidates = [
            "/usr/share/easy-rsa/easyrsa",
            "/usr/local/share/easy-rsa/easyrsa",
            "/usr/share/easy-rsa/3/easyrsa",
        ]
        for candidate in candidates:
            if Path(candidate).is_file():
                return candidate
        result = self._run_cmd(["which", "easyrsa"], check=False)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        raise PKIError(
            "Easy-RSA is not installed.",
            fix_hint="Run: apt-get update && apt-get install -y easy-rsa",
        )

    def _easyrsa(self, binary: str, config: InstallConfig, args: list) -> None:
        env = dict(os.environ)
        env.update({
            "EASYRSA_BATCH": "1",
            "EASYRSA_PKI": config.pki_dir,
        })
        # Easy-RSA rejects an external CN for build-server-full/build-client-full;
        # only the CA command may receive it.
        if "build-ca" in args:
            env["EASYRSA_REQ_CN"] = "OpenVPN-Wizard-CA"
        vars_file = Path(config.pki_dir) / "vars"
        if vars_file.exists():
            env["EASYRSA_VARS_FILE"] = str(vars_file)
        result = self._run_cmd(
            [binary, *args], env=env, timeout=900, check=False,
        )
        if result.returncode != 0:
            stderr = (result.stderr or result.stdout or "").strip()
            if "already exists" in stderr.lower():
                return
            raise PKIError(
                f"Easy-RSA command failed: {' '.join(args)}\n{stderr[-2000:]}",
                fix_hint=(
                    "Check that /etc/openvpn/pki is writable and that the "
                    "clock is correct, then re-run. No unrelated files are touched."
                ),
            )

    def _write_vars(self, config: InstallConfig, pki: Path) -> None:
        content = f"""# Managed by OpenVPN Wizard v2
set_var EASYRSA_ALGO            ec
set_var EASYRSA_CURVE           secp384r1
set_var EASYRSA_DIGEST          sha384
set_var EASYRSA_KEY_SIZE        384
set_var EASYRSA_CA_EXPIRE       3650
set_var EASYRSA_CERT_EXPIRE     825
set_var EASYRSA_CRL_DAYS        180
set_var EASYRSA_REQ_COUNTRY     "AE"
set_var EASYRSA_REQ_PROVINCE    "Dubai"
set_var EASYRSA_REQ_CITY        "Dubai"
set_var EASYRSA_REQ_ORG         "OpenVPN Wizard"
set_var EASYRSA_REQ_EMAIL       "admin@{config.domain or 'localhost'}"
set_var EASYRSA_REQ_OU          "VPN"
set_var EASYRSA_NS_SUPPORT      "no"
set_var EASYRSA_NS_COMMENT      "OpenVPN Wizard Certificate"
"""
        (pki / "vars").write_text(content)
        try:
            os.chmod(pki / "vars", 0o600)
        except OSError:
            pass

    def _sanitize_vars(self, pki: Path) -> None:
        """Remove a global EASYRSA_REQ_CN that would break client issuance."""
        vars_file = pki / "vars"
        if not vars_file.exists():
            return
        lines = [
            line for line in vars_file.read_text().splitlines()
            if not line.strip().startswith("set_var EASYRSA_REQ_CN")
        ]
        vars_file.write_text("\n".join(lines) + "\n")

    def _cert_cn(self, cert: Path) -> str:
        result = self._run_cmd(
            ["openssl", "x509", "-in", str(cert), "-noout", "-subject"],
            check=False,
        )
        match = re.search(r"CN\s*=\s*([^,/]+)", result.stdout)
        return match.group(1).strip() if match else ""

    def _adopt_ta_key(self, pki: Path) -> None:
        """Reuse an existing tls-crypt key so old profiles keep working."""
        candidates = [
            Path("/etc/openvpn/keys/ta.key"),
            Path("/etc/openvpn/ta.key"),
            Path("/root/easy-rsa/ta.key"),
        ]
        for candidate in candidates:
            if candidate.exists() and candidate.stat().st_size > 100:
                shutil.copy2(candidate, pki / "ta.key")
                try:
                    os.chmod(pki / "ta.key", 0o600)
                except OSError:
                    pass
                self.logger.info("Adopted existing TLS-crypt key from %s", candidate)
                return

    def _generate_ta_key(self, path: Path) -> None:
        for cmd in (["openvpn", "--genkey", "secret", str(path)],
                    ["openvpn", "--genkey", "--secret", str(path)]):
            result = self._run_cmd(cmd, check=False)
            if result.returncode == 0 and path.exists():
                return
        raise PKIError(
            "Could not generate the TLS-crypt key with openvpn --genkey.",
            fix_hint="Ensure the openvpn package is installed: apt-get install -y openvpn",
        )

    def _copy_runtime_assets(self, config: InstallConfig) -> None:
        pki = Path(config.pki_dir)
        openvpn = Path(config.openvpn_dir)
        openvpn.mkdir(parents=True, exist_ok=True)
        (Path("/var/lib/openvpn")).mkdir(parents=True, exist_ok=True)
        (Path("/var/log/openvpn")).mkdir(parents=True, exist_ok=True)

        assets = {
            pki / "ca.crt": openvpn / "ca.crt",
            pki / "issued" / "server.crt": openvpn / "server.crt",
            pki / "private" / "server.key": openvpn / "server.key",
            pki / "ta.key": openvpn / "ta.key",
            pki / "crl.pem": openvpn / "crl.pem",
        }
        for src, dst in assets.items():
            if not src.exists():
                raise PKIError(
                    f"Missing PKI asset: {src}",
                    fix_hint="Re-run the PKI step or restore from backup.",
                )
            shutil.copy2(src, dst)

        # OpenVPN < 2.5 expects dh.pem even with EC certificates; with ECDSA
        # we use "dh none". Only RSA PKIs need an actual DH file.
        if config.dh != "none":
            dh = Path(config.dh)
            if not dh.exists():
                result = self._run_cmd(
                    ["openssl", "dhparam", "-out", str(dh), "2048"],
                    check=False, timeout=600,
                )
                if result.returncode != 0:
                    raise PKIError(
                        "Could not generate DH parameters for the RSA certificate.",
                        fix_hint="Run: openssl dhparam -out /etc/openvpn/dh.pem 2048",
                    )
            try:
                os.chmod(dh, 0o644)
            except OSError:
                pass

        for path in ("ca.crt", "server.crt", "crl.pem"):
            try:
                os.chmod(openvpn / path, 0o644)
            except OSError:
                pass
        for path in ("server.key", "ta.key"):
            try:
                os.chmod(openvpn / path, 0o600)
            except OSError:
                pass

    def _secure_permissions(self, pki: Path, config: InstallConfig) -> None:
        for directory in (pki, pki / "private", pki / "issued"):
            if directory.exists():
                try:
                    os.chmod(directory, 0o700 if directory.name == "private" else 0o750)
                except OSError:
                    pass
        for key in (pki / "private").glob("*"):
            try:
                os.chmod(key, 0o600)
            except OSError:
                pass
        for path in (pki / "ca.crt", pki / "ta.key", pki / "crl.pem"):
            if path.exists() and path.name != "ca.crt":
                try:
                    os.chmod(path, 0o600)
                except OSError:
                    pass

    def _verify(self, config: InstallConfig, pki: Path) -> None:
        ca = str(pki / "ca.crt")
        certs = [pki / "issued" / "server.crt"] + [
            pki / "issued" / f"{u.safe_cert_name}.crt" for u in config.users
        ]
        for cert in certs:
            result = self._run_cmd(
                ["openssl", "verify", "-CAfile", ca, str(cert)], check=False,
            )
            if result.returncode != 0:
                raise PKIError(
                    f"Certificate failed verification: {cert}\n{result.stderr.strip()}",
                    fix_hint="The PKI is inconsistent; move it aside and re-run.",
                )
        crl = pki / "crl.pem"
        if not crl.exists() or "BEGIN X509 CRL" not in crl.read_text(errors="ignore"):
            raise PKIError(
                "The generated CRL is missing or invalid.",
                fix_hint="Run: cd /etc/openvpn/pki && <easyrsa> gen-crl",
            )
