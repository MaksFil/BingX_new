import json
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict

class TradeLogger:
    """Детальное логирование всех торговых решений"""

    def __init__(self, log_dir: str = "trade_logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)

        self.session_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.decisions_log = self.log_dir / f"decisions_{self.session_id}.jsonl"

        self.snapshots_dir = self.log_dir / "snapshots"
        self.snapshots_dir.mkdir(exist_ok=True)

    def log_decision(self, decision_type: str, data: Dict):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "decision_type": decision_type,
            "data": data,
        }

        with open(self.decisions_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    def save_snapshot(self, snapshot_type: str, state: Dict):
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        filename = self.snapshots_dir / f"{snapshot_type}_{timestamp}.json"

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "type": snapshot_type,
                    "state": state,
                },
                f,
                indent=2,
                ensure_ascii=False,
                default=str,
            )

    # ===== high-level helpers =====

    def log_signal_received(self, signal, validation_result: Dict):
        self.log_decision(
            "signal_received",
            {
                "symbol": signal.symbol,
                "side": signal.side,
                "entry": float(signal.entry) if signal.entry else None,
                "tp1": float(signal.tp1),
                "sl": float(signal.sl) if signal.sl else None,
                "validation": validation_result,
            },
        )

    def log_position_decision(self, decision: str, signal, reason: str, risk_check: Dict):
        self.log_decision(
            "position_decision",
            {
                "decision": decision,
                "symbol": signal.symbol,
                "reason": reason,
                "risk_check": risk_check,
            },
        )

    def log_position_opened(self, position, execution_details: Dict):
        self.log_decision(
            "position_opened",
            {
                "position_id": position.id,
                "symbol": position.symbol,
                "side": position.side,
                "entry": float(position.entry),
                "size": float(position.margin),
                "leverage": position.leverage,
                "execution": execution_details,
            },
        )

        self.save_snapshot(
            "before_open",
            {
                "position": self._position_to_dict(position),
                "execution": execution_details,
            },
        )

    def log_position_closed(self, position, close_reason: str, pnl: Decimal, execution_details: Dict):
        self.log_decision(
            "position_closed",
            {
                "position_id": position.id,
                "symbol": position.symbol,
                "reason": close_reason,
                "pnl": float(pnl),
                "pnl_percent": float(position.pnl_percent),
                "execution": execution_details,
            },
        )

        self.save_snapshot(
            "after_close",
            {
                "position": self._position_to_dict(position),
                "close_reason": close_reason,
                "pnl": float(pnl),
            },
        )

    def _position_to_dict(self, position) -> Dict:
        return {
            "id": position.id,
            "symbol": position.symbol,
            "side": position.side,
            "entry": float(position.entry),
            "tp1": float(position.tp1),
            "sl": float(position.sl),
            "margin": float(position.margin),
            "leverage": position.leverage,
            "pnl": float(position.pnl),
            "status": position.status,
        }
