"""PySide2 settings dialog for API configuration."""

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
