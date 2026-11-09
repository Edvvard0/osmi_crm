"""Значения системных настроек по умолчанию (повторяют api-contract-m11.md, «Ключи и значения»)."""

from typing import Any

DEFAULTS: dict[str, Any] = {
    "discount_alert_percent": "20.00",
    "daily_summary_time": "21:00",
    "session_retention_days": 30,
    "heatmap_thresholds": {"hours": [2, 5, 8], "actions": [5, 15, 30]},
}
