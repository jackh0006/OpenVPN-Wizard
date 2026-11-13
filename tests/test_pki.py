from __future__ import annotations

import subprocess
from pathlib import Path

from core.config import ClientSpec, InstallConfig
from steps.pki import PKIStep


def _config(tmp_path):
    return InstallConfig(
        server_ip="203.0.113.10",
        endpoint_mode="ip",
        endpoint_host="203.0.113.10",
        pki_dir=str(tmp_path / "pki"),
        users=[ClientSpec("MHH06-01", "mhh0601", "Correct-Horse-Battery-9")],
    )


def test_vars_do_not_set_global_cn(tmp_path):
    step = PKIStep()
    pki = tmp_path / "pki"
    pki.mkdir()
    step._write_vars(_config(tmp_path), pki)
    content = (pki / "vars").read_text()
    assert "EASYRSA_ALGO" in content
    assert "EASYRSA_CURVE" in content
    # A global EASYRSA_REQ_CN makes Easy-RSA reject build-server-full/client-full.
    assert "EASYRSA_REQ_CN" not in content


def test_cn_env_only_for_ca(tmp_path, monkeypatch):
    step = PKIStep()
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["env"] = kwargs.get("env", {})
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(step, "_run_cmd", fake_run)
    config = _config(tmp_path)

    step._easyrsa("easyrsa", config, ["--batch", "build-ca", "nopass"])
    assert seen["env"]["EASYRSA_REQ_CN"] == "OpenVPN-Wizard-CA"

    step._easyrsa("easyrsa", config, ["--batch", "build-server-full", "server", "nopass"])
    assert "EASYRSA_REQ_CN" not in seen["env"]
