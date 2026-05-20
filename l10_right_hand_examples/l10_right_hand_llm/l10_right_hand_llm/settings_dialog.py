"""PySide2 设置对话框 —— LLM API 配置管理。

提供图形化的 API 配置界面，支持：

- **Provider 选择** — OpenAI 或 Anthropic，切换时自动填充默认 Base URL 和 Model
- **API Key** — 密码输入框，安全存储
- **Base URL** — 支持自定义代理/中转地址
- **Model** — 模型名称（如 gpt-4o、claude-sonnet-4-20250514）

配置以 JSON 格式持久化到工作目录的 ``llm_settings.json``（已被 .gitignore
排除，避免密钥泄露）。提供 ``get_settings()`` 和 ``has_api_key()`` 两个
静态方法供其他模块直接读取配置，无需实例化对话框。

默认配置::

    OpenAI:    base_url=https://api.openai.com/v1,  model=gpt-4o
    Anthropic: base_url=https://api.anthropic.com,  model=claude-sonnet-4-20250514
"""

import json
import os

from PySide2.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QComboBox, QLineEdit,
    QDialogButtonBox, QLabel,
)

_SETTINGS_PATH = os.path.join(os.getcwd(), "llm_settings.json")

_DEFAULTS = {
    "OpenAI": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
    },
    "Anthropic": {
        "base_url": "https://api.anthropic.com",
        "model": "claude-sonnet-4-20250514",
    },
}


def _load_json() -> dict:
    if os.path.isfile(_SETTINGS_PATH):
        with open(_SETTINGS_PATH, "r") as f:
            return json.load(f)
    return {}


def _save_json(data: dict) -> None:
    with open(_SETTINGS_PATH, "w") as f:
        json.dump(data, f, indent=2)


class SettingsDialog(QDialog):
    """API configuration dialog: provider, API Key, Base URL, Model."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("LLM Settings")
        self.setMinimumWidth(450)
        self._build_ui()
        self._load_settings()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        form = QFormLayout()

        self.provider_combo = QComboBox()
        self.provider_combo.addItems(["OpenAI", "Anthropic"])
        self.provider_combo.currentTextChanged.connect(self._on_provider_changed)
        form.addRow("Provider:", self.provider_combo)

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("Enter API Key...")
        form.addRow("API Key:", self.api_key_edit)

        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText("https://...")
        form.addRow("Base URL:", self.base_url_edit)

        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("Model name")
        form.addRow("Model:", self.model_edit)

        layout.addLayout(form)

        hint = QLabel("Switching provider auto-fills default Base URL and Model.")
        hint.setStyleSheet("color: #888; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._save_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_provider_changed(self, provider: str):
        defaults = _DEFAULTS.get(provider, {})
        self.base_url_edit.setText(defaults.get("base_url", ""))
        self.model_edit.setText(defaults.get("model", ""))

    def _load_settings(self):
        data = _load_json()
        provider = data.get("provider", "OpenAI")
        self.provider_combo.setCurrentText(provider)
        self.api_key_edit.setText(data.get("api_key", ""))
        self.base_url_edit.setText(
            data.get("base_url", _DEFAULTS[provider]["base_url"])
        )
        self.model_edit.setText(
            data.get("model", _DEFAULTS[provider]["model"])
        )

    def _save_and_accept(self):
        _save_json({
            "provider": self.provider_combo.currentText(),
            "api_key": self.api_key_edit.text().strip(),
            "base_url": self.base_url_edit.text().strip(),
            "model": self.model_edit.text().strip(),
        })
        self.accept()

    @staticmethod
    def get_settings() -> dict:
        data = _load_json()
        provider = data.get("provider", "OpenAI")
        return {
            "provider": provider,
            "api_key": data.get("api_key", ""),
            "base_url": data.get(
                "base_url", _DEFAULTS[provider]["base_url"]
            ),
            "model": data.get(
                "model", _DEFAULTS[provider]["model"]
            ),
        }

    @staticmethod
    def has_api_key() -> bool:
        return bool(_load_json().get("api_key"))
