"""Core module for the VPN installer."""

from core.config import (
    ClientSpec,
    InstallConfig,
    validate_access_mode,
    validate_auth_mode,
    validate_config,
    validate_hostname,
    validate_ip,
    validate_ipv4,
    validate_password,
    validate_port,
    validate_profile_name,
    validate_transport,
    validate_username,
    validate_fqdn,
    validate_client_name,
)
from core.state import InstallState, StepState, StateManager
from core.logger import setup_logger, get_logger, StepLogger, log_command, log_output
from core.exceptions import (
    InstallerError, UserInputError, ValidationError, SystemError,
    NetworkError, ConfigError, ServiceError, CryptoError,
    RollbackError, StateError, UserAbortError, PortConflictError,
    HAProxyConflictError, PKIError, format_error, ERROR_TITLES,
)

__all__ = [
    "ClientSpec", "InstallConfig", "validate_config",
    "validate_fqdn", "validate_ip", "validate_ipv4", "validate_username", "validate_password",
    "validate_client_name", "validate_hostname", "validate_port",
    "validate_transport", "validate_auth_mode", "validate_access_mode",
    "validate_profile_name", "InstallState", "StepState", "StateManager",
    "setup_logger", "get_logger", "StepLogger", "log_command", "log_output",
    "InstallerError", "UserInputError", "ValidationError", "SystemError",
    "NetworkError", "ConfigError", "ServiceError", "CryptoError",
    "RollbackError", "StateError", "UserAbortError", "PortConflictError",
    "HAProxyConflictError", "PKIError", "format_error", "ERROR_TITLES",
]
