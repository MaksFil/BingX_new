import asyncio
import logging
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple

# Если используете UTC-помеченные даты
UTC = timezone.utc

@dataclass
class RiskLimits:
    """Лимиты риск-менеджмента"""
    max_daily_loss_percent: Decimal = Decimal("2.0")  # 2% от капитала в день
    max_total_exposure_percent: Decimal = Decimal("50.0")  # 50% общая экспозиция
    emergency_stop_percent: Decimal = Decimal("5.0")  # Аварийная остановка при 5% просадке
    max_position_size_percent: Decimal = Decimal("5.0")  # 5% на одну позицию
    max_positions: int = 5
    daily_loss_reset_hour: int = 0  # Час сброса дневной статистики (UTC)


class RiskManager:
    """Комплексный менеджер рисков с аварийной остановкой"""

    def __init__(self, initial_balance: Decimal, limits: Optional[RiskLimits] = None):
        self.limits = limits or RiskLimits()
        self.initial_balance = initial_balance
        self.starting_daily_balance = initial_balance
        self.daily_pnl = Decimal("0")
        self.total_exposure = Decimal("0")
        self.peak_balance = initial_balance
        self.is_emergency_stopped = False
        self.last_reset_date = datetime.now(UTC).date()
        self.emergency_callback = None  # Будет установлен ботом

        # История для анализа
        self.risk_events: List[Dict[str, Any]] = []
        self.daily_stats: Dict = {}

        logging.info(f"🛡️ RiskManager initialized with balance: {initial_balance} USDT")
        logging.info(f"   Max daily loss: {self.limits.max_daily_loss_percent}%")
        logging.info(f"   Max exposure: {self.limits.max_total_exposure_percent}%")
        logging.info(f"   Emergency stop at: {self.limits.emergency_stop_percent}%")

    async def execute_emergency_stop(self, bot) -> Dict:
        """
        Выполнение аварийной остановки:
        - Закрываем ВСЕ открытые позиции
        - Отменяем ВСЕ pending ордера
        - Блокируем новые сделки
        """
        logging.critical("🚨 EXECUTING EMERGENCY STOP!")

        results = {"positions_closed": 0, "orders_cancelled": 0, "errors": []}

        # 1. Закрываем все открытые позиции
        for position_id in list(bot.open_positions.keys()):
            try:
                await bot.close_position_manual(position_id, "EMERGENCY STOP")
                results["positions_closed"] += 1
            except Exception as e:
                results["errors"].append(f"Failed to close {position_id}: {e}")

        # 2. Отменяем все pending ордера
        if bot.exchange and not bot.config.demo_mode:
            try:
                open_orders = await bot.exchange.fetch_open_orders()
                for order in open_orders:
                    try:
                        await bot.exchange.cancel_order(order["id"], order["symbol"])
                        results["orders_cancelled"] += 1
                    except Exception as e:
                        results["errors"].append(f"Failed to cancel order {order['id']}: {e}")
            except Exception as e:
                results["errors"].append(f"Failed to fetch open orders: {e}")

        # 3. Уведомляем пользователя
        if hasattr(bot, "websocket_manager"):
            await bot.websocket_manager.notify(
                title="🚨 EMERGENCY STOP EXECUTED",
                message=f"Closed {results['positions_closed']} positions, cancelled {results['orders_cancelled']} orders",
                level="error",
            )

        logging.critical(f"Emergency stop results: {results}")
        return results

    def check_daily_reset(self, current_balance: Decimal):
        """Проверка и сброс дневных лимитов"""
        now = datetime.now(UTC)
        current_date = now.date()

        if current_date > self.last_reset_date:
            # Сброс дневной статистики
            self.daily_stats[self.last_reset_date.isoformat()] = {
                "daily_pnl": float(self.daily_pnl),
                "starting_balance": float(self.starting_daily_balance),
                "ending_balance": float(current_balance),
                "was_emergency_stopped": self.is_emergency_stopped,
            }

            self.starting_daily_balance = current_balance
            self.daily_pnl = Decimal("0")
            self.last_reset_date = current_date
            self.is_emergency_stopped = False

            logging.info(f"📅 Daily reset completed. New daily balance: {current_balance} USDT")

    def check_emergency_stop(self, current_balance: Decimal) -> Tuple[bool, str]:
        """Проверка условий аварийной остановки"""
        if self.is_emergency_stopped:
            return True, "Emergency stop already active"

        drawdown = (self.peak_balance - current_balance) / self.peak_balance * 100

        if drawdown >= self.limits.emergency_stop_percent:
            self.is_emergency_stopped = True
            msg = f"🚨 EMERGENCY STOP! Drawdown: {drawdown:.2f}% (limit: {self.limits.emergency_stop_percent}%)"
            logging.critical(msg)

            self.risk_events.append({
                "timestamp": datetime.now(UTC).isoformat(),
                "event": "emergency_stop",
                "drawdown": float(drawdown),
                "balance": float(current_balance),
                "peak_balance": float(self.peak_balance),
            })

            if self.emergency_callback:
                asyncio.create_task(self.emergency_callback())

            return True, msg

        return False, ""

    def check_daily_loss_limit(self, current_balance: Decimal) -> Tuple[bool, str]:
        """Проверка дневного лимита убытков"""
        daily_loss = self.starting_daily_balance - current_balance
        daily_loss_percent = (daily_loss / self.starting_daily_balance) * 100

        if daily_loss_percent >= self.limits.max_daily_loss_percent:
            msg = f"⛔ Daily loss limit reached: {daily_loss_percent:.2f}% (limit: {self.limits.max_daily_loss_percent}%)"
            logging.warning(msg)

            self.risk_events.append({
                "timestamp": datetime.now(UTC).isoformat(),
                "event": "daily_loss_limit",
                "loss_percent": float(daily_loss_percent),
                "loss_usdt": float(daily_loss),
            })

            return False, msg

        return True, ""

    def can_open_position(self, position_size: Decimal, current_balance: Decimal) -> Tuple[bool, str]:
        """Комплексная проверка возможности открытия позиции"""
        is_stopped, stop_msg = self.check_emergency_stop(current_balance)
        if is_stopped:
            return False, stop_msg

        can_trade, daily_msg = self.check_daily_loss_limit(current_balance)
        if not can_trade:
            return False, daily_msg

        position_percent = (position_size / current_balance) * 100
        if position_percent > self.limits.max_position_size_percent:
            return False, f"Position size {position_percent:.2f}% exceeds limit {self.limits.max_position_size_percent}%"

        new_exposure = self.total_exposure + position_size
        exposure_percent = (new_exposure / current_balance) * 100
        if exposure_percent > self.limits.max_total_exposure_percent:
            return False, f"Total exposure {exposure_percent:.2f}% exceeds limit {self.limits.max_total_exposure_percent}%"

        return True, "OK"

    def register_position_open(self, position_size: Decimal):
        """Регистрация открытия позиции"""
        self.total_exposure += position_size
        logging.info(f"📊 Position opened. Total exposure: {self.total_exposure} USDT")

    def register_position_close(self, position_size: Decimal, pnl: Decimal, current_balance: Decimal):
        """Регистрация закрытия позиции"""
        self.total_exposure = max(Decimal("0"), self.total_exposure - position_size)
        self.daily_pnl += pnl

        if current_balance > self.peak_balance:
            self.peak_balance = current_balance

        logging.info(f"📊 Position closed. PnL: {pnl:.2f} USDT. Daily PnL: {self.daily_pnl:.2f} USDT")

    def get_risk_report(self, current_balance: Decimal) -> Dict:
        """Детальный отчет по рискам"""
        drawdown = (self.peak_balance - current_balance) / self.peak_balance * 100
        daily_loss_percent = (self.starting_daily_balance - current_balance) / self.starting_daily_balance * 100
        exposure_percent = (self.total_exposure / current_balance) * 100 if current_balance > 0 else Decimal("0")

        return {
            "current_balance": float(current_balance),
            "peak_balance": float(self.peak_balance),
            "drawdown_percent": float(drawdown),
            "daily_pnl": float(self.daily_pnl),
            "daily_loss_percent": float(daily_loss_percent),
            "total_exposure": float(self.total_exposure),
            "exposure_percent": float(exposure_percent),
            "is_emergency_stopped": self.is_emergency_stopped,
            "limits": {
                "max_daily_loss": float(self.limits.max_daily_loss_percent),
                "max_exposure": float(self.limits.max_total_exposure_percent),
                "emergency_stop": float(self.limits.emergency_stop_percent),
            },
            "status": "EMERGENCY_STOPPED" if self.is_emergency_stopped else "ACTIVE",
        }
