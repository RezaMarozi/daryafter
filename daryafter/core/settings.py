"""User settings (stored as JSON inside the database)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import asdict, dataclass, field, fields

from ..branding import DEFAULT_USER_AGENT
from ..paths import default_download_dir
from .transport import NetworkConfig

_KEY = "app_settings"
_PBKDF_ROUNDS = 200_000


@dataclass
class Settings:
    # downloads
    download_dir: str = ""                 # "" = the user's Downloads folder
    auto_categorize: bool = True
    ask_name_each_time: bool = True
    connections: int = 8
    max_concurrent: int = 3
    global_speed_limit: int = 0            # bytes/second, 0 = unlimited
    max_speed_mode: bool = False
    retry_max: int = 10                    # -1 = never give up
    retry_base_delay: float = 2.0
    set_file_time: bool = True
    prevent_sleep: bool = True
    resume_on_start: bool = False
    # network
    proxy_mode: str = "system"             # system | none | manual
    proxy_url: str = ""
    use_http2: bool = False
    verify_tls: bool = True
    user_agent: str = DEFAULT_USER_AGENT
    # interface
    theme: str = "system"                  # system | light | dark
    language: str = "en"
    clipboard_watch: bool = True
    notify_on_complete: bool = True
    show_summary: bool = True
    tray_enabled: bool = True
    minimize_to_tray: bool = False
    window_geometry: str = ""
    # privacy
    start_private: bool = False
    clear_history_on_exit: bool = False
    remember_passwords: bool = True
    lock_salt: str = ""
    lock_hash: str = ""
    lock_after_minutes: int = 0            # lock after this many minutes without keyboard/mouse use; 0 = never
    lock_on_minimize: bool = True          # lock when the window is minimized or sent to the tray
    # schedule: list of rules (see core/schedule.py); stored as plain dicts
    schedule: list = field(default_factory=list)

    # ---- helpers --------------------------------------------------------
    def resolved_download_dir(self) -> str:
        return self.download_dir or str(default_download_dir())

    def network_config(self) -> NetworkConfig:
        return NetworkConfig(proxy_mode=self.proxy_mode, proxy_url=self.proxy_url,
                             http2=self.use_http2, verify_tls=self.verify_tls)

    def copy(self) -> "Settings":
        return Settings(**asdict(self))

    # ---- app lock -------------------------------------------------------
    @property
    def lock_enabled(self) -> bool:
        return bool(self.lock_hash)

    def set_password(self, password: str) -> None:
        if not password:
            self.lock_salt = self.lock_hash = ""
            return
        salt = os.urandom(16)
        self.lock_salt = base64.b64encode(salt).decode("ascii")
        self.lock_hash = base64.b64encode(
            hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF_ROUNDS)).decode("ascii")

    def check_password(self, password: str) -> bool:
        if not self.lock_hash:
            return True
        try:
            salt = base64.b64decode(self.lock_salt)
            expected = base64.b64decode(self.lock_hash)
        except ValueError:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF_ROUNDS)
        return hmac.compare_digest(actual, expected)

    # ---- persistence ----------------------------------------------------
    @classmethod
    def load(cls, storage) -> "Settings":
        raw = storage.get_setting(_KEY)
        if not raw:
            return cls()
        try:
            data = json.loads(raw)
        except ValueError:
            return cls()
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})

    def save(self, storage) -> None:
        storage.set_setting(_KEY, json.dumps(asdict(self)))
