"""Certificate lifecycle helpers (issue, revoke, inspect)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from core.config import InstallConfig
from core.logger import get_logger
from steps.openvpn import OpenVPNStep


class CertManager:
    def __init__(self, config: InstallConfig):
        self.config = config
        self.logger = get_logger()
        self.pki_dir = Path(config.pki_dir)

    def _easyrsa(self, args: list) -> subprocess.CompletedProcess:
        binary = "/usr/share/easy-rsa/easyrsa"
        if not Path(binary).exists():
            found = shutil.which("easyrsa")
            if not found:
                raise RuntimeError("easy-rsa is not installed (apt-get install -y easy-rsa)")
            binary = found
        env = dict(os.environ)
        env.update({"EASYRSA_BATCH": "1", "EASYRSA_PKI": str(self.pki_dir)})
        if (self.pki_dir / "vars").exists():
            env["EASYRSA_VARS_FILE"] = str(self.pki_dir / "vars")
        result = subprocess.run([binary, *args], capture_output=True, text=True,
                                env=env, check=False)
        if result.returncode != 0:
            raise RuntimeError(
                f"Easy-RSA failed: {' '.join(args)}\n"
                f"{(result.stderr or result.stdout)[-1500:]}"
            )
        return result

    def _sanitize_vars(self) -> None:
        vars_file = self.pki_dir / "vars"
        if not vars_file.exists():
            return
        lines = [
            line for line in vars_file.read_text().splitlines()
            if not line.strip().startswith("set_var EASYRSA_REQ_CN")
        ]
        vars_file.write_text("\n".join(lines) + "\n")

    def issue_client_cert(self, username: str) -> tuple[str, str]:
        self._sanitize_vars()
        if not (self.pki_dir / "issued" / f"{username}.crt").exists():
            self._easyrsa(["--batch", "build-client-full", username, "nopass"])
        cert = (self.pki_dir / "issued" / f"{username}.crt").read_text()
        key = (self.pki_dir / "private" / f"{username}.key").read_text()
        return cert, key

    def revoke_cert(self, username: str) -> None:
        self._easyrsa(["--batch", "revoke", username])
        self._easyrsa(["gen-crl"])
        crl = self.pki_dir / "crl.pem"
        shutil.copy2(crl, Path(self.config.openvpn_dir) / "crl.pem")
        os.chmod(Path(self.config.openvpn_dir) / "crl.pem", 0o644)
        subprocess.run(["systemctl", "reload-or-restart", OpenVPNStep.openvpn_service_name()],
                       capture_output=True, check=False)

    def get_cert_info(self, username: str) -> dict:
        cert_path = self.pki_dir / "issued" / f"{username}.crt"
        if not cert_path.exists():
            return {}
        result = subprocess.run(
            ["openssl", "x509", "-in", str(cert_path), "-noout",
             "-subject", "-dates", "-serial"],
            capture_output=True, text=True, check=False,
        )
        info = {"username": username}
        for line in result.stdout.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                info[key.strip()] = value.strip()
        return info

    def list_certs(self) -> list:
        issued = self.pki_dir / "issued"
        if not issued.exists():
            return []
        return [self.get_cert_info(path.stem) for path in sorted(issued.glob("*.crt"))]
