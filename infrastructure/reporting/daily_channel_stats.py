import json
import logging
from pathlib import Path
from collections import defaultdict
from datetime import datetime, date


class DailyChannelStats:
    """
    Хранение и генерация дневной статистики по каналам
    """

    def __init__(self, data_dir: str = "data/daily_stats"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.current_date = date.today()
        self.stats = self._empty_stats()
        self._load()

    def add_trade(
        self,
        channel_id: str,
        channel_name: str,
        symbol: str,
        side: str,
        pnl: float,
        entry: float,
        exit_price: float,
    ):
        self._check_new_day()

        channel = self.stats[channel_id]
        channel["channel_name"] = channel_name

        trade = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "symbol": symbol,
            "side": side,
            "entry": entry,
            "exit": exit_price,
            "pnl": round(pnl, 2),
        }

        channel["trades"].append(trade)

        if pnl > 0:
            channel["profitable"] += 1
            channel["total_profit"] += pnl
        else:
            channel["losing"] += 1
            channel["total_loss"] += abs(pnl)

        self._save()

    # ---------------- internals ----------------

    def _empty_stats(self):
        return defaultdict(lambda: {
            "channel_name": "",
            "profitable": 0,
            "losing": 0,
            "total_profit": 0.0,
            "total_loss": 0.0,
            "trades": [],
        })

    def _filename(self):
        return self.data_dir / f"stats_{self.current_date.isoformat()}"

    def _check_new_day(self):
        if date.today() != self.current_date:
            self._save()
            self.current_date = date.today()
            self.stats = self._empty_stats()

    def _save(self):
        json_file = self._filename().with_suffix(".json")
        txt_file = self._filename().with_suffix(".txt")

        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(dict(self.stats), f, indent=2, ensure_ascii=False)

        with open(txt_file, "w", encoding="utf-8") as f:
            f.write(self._generate_report())

    def _load(self):
        json_file = self._filename().with_suffix(".json")
        if json_file.exists():
            with open(json_file, "r", encoding="utf-8") as f:
                self.stats = defaultdict(lambda: self._empty_stats()[""], json.load(f))

    def _generate_report(self) -> str:
        lines = [
            "=" * 80,
            f"📊 DAILY CHANNEL STATS — {self.current_date}",
            "=" * 80,
            "",
        ]

        for channel_id, s in self.stats.items():
            if not s["trades"]:
                continue

            net = s["total_profit"] - s["total_loss"]
            winrate = (
                s["profitable"] / len(s["trades"]) * 100
                if s["trades"] else 0
            )

            lines.extend([
                f"{s['channel_name']} ({channel_id})",
                f"Trades: {len(s['trades'])} | Winrate: {winrate:.1f}%",
                f"PNL: {net:+.2f}",
                "",
            ])

        return "\n".join(lines)
