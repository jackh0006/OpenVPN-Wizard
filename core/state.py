"""
Installation state management with resume support.

The state file is written with mode 600 because, during an in-progress
install, it can contain not-yet-applied VPN passwords.  Once the install is
complete the passwords are cleared from the persisted copy.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.config import ClientSpec, InstallConfig

STATE_VERSION = "2.1.0"


@dataclass
class StepState:
    name: str
    display_name: str
    completed: bool = False
    failed: bool = False
    skipped: bool = False
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    error: Optional[str] = None
    rollback_data: Dict[str, Any] = field(default_factory=dict)
    output: List[str] = field(default_factory=list)


@dataclass
class InstallState:
    config: Optional[InstallConfig] = None

    welcome_done: bool = False
    privacy_done: bool = False
    params_done: bool = False
    confirm_done: bool = False
    install_done: bool = False
    completed: bool = False

    steps: Dict[str, StepState] = field(default_factory=dict)

    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    version: str = STATE_VERSION

    backup_dir: str = "/var/backups/vpn-installer"
    rollback_points: List[str] = field(default_factory=list)

    def __post_init__(self):
        if isinstance(self.config, dict):
            self.config = _config_from_dict(self.config)

    @property
    def current_step(self) -> Optional[str]:
        for step_id, step in self.steps.items():
            if step.start_time and not step.end_time:
                return step_id
        return None

    @property
    def completed_steps(self) -> List[str]:
        return [sid for sid, s in self.steps.items() if s.completed]

    @property
    def failed_steps(self) -> List[str]:
        return [sid for sid, s in self.steps.items() if s.failed]

    def mark_step_start(self, step_id: str, rollback_data: Dict[str, Any] = None):
        if step_id not in self.steps:
            self.steps[step_id] = StepState(name=step_id, display_name=step_id)
        self.steps[step_id].start_time = time.time()
        self.steps[step_id].rollback_data = rollback_data or {}
        self.updated_at = datetime.now().isoformat()

    def mark_step_complete(self, step_id: str, output: List[str] = None):
        if step_id in self.steps:
            self.steps[step_id].completed = True
            self.steps[step_id].end_time = time.time()
            if output:
                self.steps[step_id].output = output
        self.updated_at = datetime.now().isoformat()

    def mark_step_failed(self, step_id: str, error: str):
        if step_id in self.steps:
            self.steps[step_id].failed = True
            self.steps[step_id].end_time = time.time()
            self.steps[step_id].error = error
        self.updated_at = datetime.now().isoformat()

    def mark_step_skipped(self, step_id: str):
        if step_id in self.steps:
            self.steps[step_id].skipped = True
            self.steps[step_id].end_time = time.time()
        self.updated_at = datetime.now().isoformat()

    def add_rollback_point(self, description: str):
        self.rollback_points.append(f"{datetime.now().isoformat()}: {description}")
        self.updated_at = datetime.now().isoformat()

    def to_dict(self, redact_secrets: bool = False) -> Dict[str, Any]:
        data = asdict(self)
        if self.config:
            data["config"] = asdict(self.config)
            if redact_secrets:
                for user in data["config"].get("users", []):
                    user["password"] = ""
                data["config"]["admin_pass"] = ""
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InstallState":
        data = dict(data)
        config_data = data.pop("config", None)
        known = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known}
        state = cls(**filtered)
        if config_data:
            state.config = _config_from_dict(config_data)
        steps: Dict[str, StepState] = {}
        for sid, sdata in (data.get("steps") or {}).items():
            try:
                steps[sid] = StepState(**{
                    k: v for k, v in sdata.items()
                    if k in {f.name for f in fields(StepState)}
                })
            except Exception:
                continue
        state.steps = steps
        return state


def _config_from_dict(data: Dict[str, Any]) -> InstallConfig:
    """Tolerate state files written by v1.0/v1.1."""
    data = dict(data)
    users = data.get("users") or []
    parsed_users: List[ClientSpec] = []
    for item in users:
        if isinstance(item, ClientSpec):
            parsed_users.append(item)
        elif isinstance(item, dict):
            parsed_users.append(ClientSpec(**{
                k: v for k, v in item.items()
                if k in {"name", "username", "password", "cert_name"}
            }))
    data["users"] = parsed_users

    # Map removed v1 fields onto the new model.
    if not data.get("endpoint_host"):
        data["endpoint_host"] = data.get("domain") or data.get("server_ip", "")
    if "haproxy_port" in data and "public_port" not in data:
        data["public_port"] = data.pop("haproxy_port")
    if not data.get("public_port"):
        data["public_port"] = 443
    if not data.get("profiles_dir"):
        data["profiles_dir"] = "/etc/openvpn/clients"

    known = {f.name for f in fields(InstallConfig)}
    filtered = {k: v for k, v in data.items() if k in known}
    # v1 used vpn_user/vpn_pass/client_name; keep them if users is empty.
    if not filtered.get("users"):
        name = data.get("client_name") or data.get("profile_prefix") or "MHH06"
        filtered["users"] = [ClientSpec(
            name=name,
            username=data.get("vpn_user") or "vpnuser",
            password=data.get("vpn_pass") or "",
        )]
    return InstallConfig(**filtered)


class StateManager:
    def __init__(self, state_file: str = "/var/lib/vpn-installer/state.json"):
        self.state_file = Path(state_file)

    def _ensure_dir(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.state_file.parent, 0o700)
        except OSError:
            pass

    def save(self, state: InstallState, redact_secrets: bool = False):
        state.updated_at = datetime.now().isoformat()
        self._ensure_dir()
        tmp = self.state_file.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(state.to_dict(redact_secrets=redact_secrets), fh, indent=2)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.state_file)
        except Exception as exc:  # never abort an install for a state write
            print(f"[yellow]Warning: could not save state: {exc}[/yellow]")

    def load(self) -> Optional[InstallState]:
        if not self.state_file.exists():
            return None
        try:
            with open(self.state_file, "r", encoding="utf-8") as fh:
                return InstallState.from_dict(json.load(fh))
        except Exception as exc:
            print(f"[yellow]Warning: could not load state: {exc}[/yellow]")
            return None

    def clear(self):
        if self.state_file.exists():
            self.state_file.unlink()

    def backup(self, suffix: str = None) -> Optional[Path]:
        if not self.state_file.exists():
            return None
        suffix = suffix or datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.state_file.with_suffix(f".bak.{suffix}.json")
        backup_path.write_text(self.state_file.read_text())
        os.chmod(backup_path, 0o600)
        return backup_path
