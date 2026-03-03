import os
import time
import json
import logging
import traceback
import asyncio
from decimal import Decimal
from datetime import datetime, timezone
from typing import Dict, List, Optional

from models.positions import PaperPosition, PositionStatus
from models.trading import TradingConfig

# Импорты для RiskManager и Signal, websocket_manager нужно реализовать отдельно
from core.safety.risk_manager import RiskManager, RiskLimits
from utils.signal_parser import Signal
from api.websocket_manager import websocket_manager

# Декоратор для обработки ошибок
def error_handler(func):
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            logging.error(f"❌ Ошибка в {func.__name__}: {e}\n{traceback.format_exc()}")
    return wrapper


class PaperTradingMode:
    """Продвинутый Paper Trading с сохранением состояния и трейлингом."""

    def __init__(self, bot):
        self.bot = bot
        self.enabled = False
        self.start_balance = Decimal('1000')
        self.current_balance = Decimal('1000')
        self.paper_positions: Dict[str, PaperPosition] = {}
        self.paper_trades_history: List[Dict] = []
        self.monitor_task = None
        self.risk_manager: Optional[RiskManager] = None

    def get_recent_trades(self, limit: int = 10) -> List[Dict]:
        """Возвращает последние N сделок из истории."""
        return self.paper_trades_history[-limit:]

    def enable(self, starting_balance: Decimal = Decimal('1000')):
        self.enabled = True
        self.start_balance = starting_balance
        self.current_balance = starting_balance
        # Создаем собственный RiskManager для Paper Trading, используя лимиты по умолчанию
        try:
            self.risk_manager = RiskManager(initial_balance=starting_balance, limits=RiskLimits())
            logging.info(f"🛡️ RiskManager for Paper Trading ENABLED with balance {starting_balance}")
        except Exception as e:
            logging.error(f"❌ Failed to initialize RiskManager for Paper Trading: {e}")
            self.risk_manager = None
        #if self.monitor_task is None or self.monitor_task.done():
          #  self.monitor_task = asyncio.create_task(self.monitor_positions())
        logging.info(f"📊 Paper Trading ENABLED with {starting_balance} USDT")

    def disable(self):
        self.enabled = False
        self.risk_manager = None
        if self.monitor_task and not self.monitor_task.done():
            self.monitor_task.cancel()
        logging.info("📊 Paper Trading DISABLED")

    async def open_paper_position(self, exchange, signal: Signal) -> Optional[str]:
        logging.info(f"--> [PAPER_OPEN] Открытие Paper-позиции для {signal.symbol}...")
        try:
            # ИЗМЕНЕНИЕ: Прямой вызов get_current_price с передачей exchange
            real_price = await self.bot.get_current_price(exchange, signal.symbol)
            if not real_price:
                logging.error(f"----> [PAPER_OPEN] 🔴 Не удалось получить реальную цену для {signal.symbol}. Отмена.")
                return None
            logging.info(f"----> [PAPER_OPEN] Цена для {signal.symbol} получена: {real_price}")

            margin = self.bot.config.trade_amount
            if not self.risk_manager:
                logging.warning("⚠️ [PAPER_OPEN] RiskManager for Paper Trading is not enabled. Aborting.")
                return None

                # Проверка риск-менеджера (используем текущий баланс)
            can_open, risk_msg = self.risk_manager.can_open_position(margin, self.current_balance)
            if not can_open:
                logging.warning(f"❌ [PAPER_OPEN] Risk check FAILED: {risk_msg}. Signal for {signal.symbol} skipped.")
                # Уведомляем UI
                await websocket_manager.notify("Risk Check Failed", f"Paper trade for {signal.symbol} skipped: {risk_msg}", "warning")
                return None

            logging.info(f"✅ [PAPER_OPEN] Risk check PASSED for {signal.symbol}")
            if margin > self.current_balance:
                logging.warning(f"⚠️ Insufficient paper balance: {self.current_balance} < {margin}")
                return None

            tp_levels = [{'price': signal.tp1, 'percent': self.bot.config.tp1_close_percent, 'number': 1, 'hit': False}]
            if hasattr(signal, 'tp2') and signal.tp2:
                tp_levels.append({'price': signal.tp2, 'percent': 50, 'number': 2, 'hit': False})
            if hasattr(signal, 'tp3') and signal.tp3:
                tp_levels.append({'price': signal.tp3, 'percent': 100, 'number': 3, 'hit': False})

            position = PaperPosition(
                symbol=signal.symbol,
                entry_price=real_price,
                direction=signal.side,
                size=margin,
                sl=signal.sl,
                tp_levels=tp_levels,
                leverage=signal.leverage,
                channel_id=str(signal.channel_id) if hasattr(signal, 'channel_id') else None,
                channel_name=signal.channel_name if hasattr(signal, 'channel_name') else None
            )
            if self.risk_manager:
                self.risk_manager.register_position_open(margin)

            # <<< ДОБАВЬТЕ ЭТУ СТРОКУ >>>
            logging.info(f"!!! DEBUG PAPER_POS: Created PaperPosition with tp_levels: {position.tp_levels}")

            self.paper_positions[position.id] = position
            logging.info(f"📝 Paper position OPENED: {signal.symbol} at REAL price {real_price}")
            return position.id
        except Exception as e:
            logging.error(f"Error opening paper position: {e}\n{traceback.format_exc()}")
            return None

    async def check_position_sl_tp(self, position: PaperPosition, current_price: Decimal):
        """Выполняет проверку SL/TP для одной paper-позиции (для real-time стрима)."""
        if position.status == PositionStatus.CLOSED:
            return

        try:
            # 1. Трейлинг-стоп
            if position.trailing_stop.enabled:
                position.update_trailing_stop(current_price, trail_percent=Decimal('2.0'))
                if position.check_trailing_stop_hit(current_price):
                    self.process_position_close(position, current_price, "Trailing Stop Hit")
                    await self.bot.broadcast_positions_update() # Уведомляем UI
                    return

            # 2. Обычный SL
            if not position.trailing_stop.enabled and position.sl:
                sl_hit = (position.direction == 'BUY' and current_price <= position.sl) or \
                         (position.direction == 'SELL' and current_price >= position.sl)
                if sl_hit:
                    self.process_position_close(position, current_price, "Stop Loss Hit")
                    await self.bot.broadcast_positions_update() # Уведомляем UI
                    return

            # 3. TP уровни
            for tp_level in position.tp_levels:
                if tp_level['hit']: continue

                tp_hit = (position.direction == 'BUY' and current_price >= tp_level['price']) or \
                         (position.direction == 'SELL' and current_price <= tp_level['price'])

                if tp_hit:
                    self.process_tp_hit(position.id, tp_level['number'], current_price)
                    if position.status == PositionStatus.CLOSED:
                        await self.bot.broadcast_positions_update() # Уведомляем UI
                        break

        except Exception as e:
            logging.error(f"Ошибка в paper check_position_sl_tp для {position.symbol}: {e}")

    @error_handler
    async def monitor_positions(self, exchange, all_prices: Dict[str, Decimal]):
        """
        ФИНАЛЬНАЯ ВЕРСИЯ: Мониторинг paper-позиций (БЕЗ MOCK-ЦІН).
        """
        if not self.enabled:
            return
            # --- ИНТЕГРАЦИЯ RISK MANAGER (ПЕРИОДИЧЕСКИЕ ПРОВЕРКИ) ---
            if self.risk_manager:
                try:
                    # 1. Проверяем сброс дневной статистики
                    self.risk_manager.check_daily_reset(self.current_balance)

                    # 2. Проверяем аварийную остановку (EMERGENCY STOP)
                    is_stopped, stop_msg = self.risk_manager.check_emergency_stop(self.current_balance)
                    if is_stopped:
                        logging.critical(f"🚨 [PAPER] EMERGENCY STOP TRIGGERED: {stop_msg}")
                        await websocket_manager.notify("PAPER EMERGENCY STOP", stop_msg, "error")

                        # Закрываем все открытые paper-позиции
                        positions_to_close = [
                            pos.id for pos in self.paper_positions.values()
                            if pos.status != PositionStatus.CLOSED
                        ]
                        logging.info(f"🚨 [PAPER] Closing {len(positions_to_close)} open paper positions...")
                        for pos_id in positions_to_close:
                            await self.close_paper_position(pos_id, reason="EMERGENCY STOP")

                        # Отключаем paper trading, чтобы он не открывал новые
                        self.disable()
                        logging.critical("🚨 [PAPER] All paper positions closed and paper trading disabled.")
                        return # Немедленно выходим из мониторинга

                except Exception as e:
                    logging.error(f"❌ Error in Paper RiskManager check: {e}")

        positions_to_monitor = list(self.paper_positions.values())

        for position in positions_to_monitor:
            if position.status == PositionStatus.CLOSED:
                continue

            try:
                # 1. Беремо ціну з готового словника
                current_price = all_prices.get(position.symbol)

                # 2. ЯКЩО ЦІНИ НЕМАЄ - ПРОПУСКАЄМО
                # Real-time потік все одно працює. Немає цін - немає перевірки.
                if not current_price:
                    logging.debug(f"Немає ціни для {position.symbol} у 10-сек циклі, пропускаю.")
                    continue

                # 3. Оновлюємо PnL для UI (основна перевірка SL/TP йде в real-time потоці)
                position.get_unrealized_pnl(current_price)

            except Exception as e:
                logging.error(f"Error monitoring paper position PnL {position.symbol}: {e}")
                continue

    def process_tp_hit(self, position_id: str, tp_level_number: int, current_price: Decimal):
        """Обработка достижения TP для paper-позиции."""
        if position_id not in self.paper_positions:
            return

        position = self.paper_positions[position_id]
        if position.status == PositionStatus.CLOSED:
            return

        # Находим нужный уровень TP
        tp_level = next((level for level in position.tp_levels if level.get('number') == tp_level_number), None)
        if not tp_level or tp_level['hit']:
            return

        percent_to_close = tp_level['percent']
        reason = f"TP{tp_level_number} Hit"

        # Частично закрываем позицию
        position.close_partial(percent_to_close, current_price, reason)
        tp_level['hit'] = True

        # Активируем трейлинг после первого TP, если нужно
        if tp_level_number == 1 and not position.trailing_stop.enabled:
            position.activate_trailing_stop(breakeven=True)

        # Если позиция полностью закрылась, логгируем в историю
        if position.status == PositionStatus.CLOSED:
            self._log_trade_to_history(position, current_price, "All TPs Hit")

    async def close_paper_position(self, position_id: str, reason: str = "Manual Close"):
        if position_id not in self.paper_positions: return False
        position = self.paper_positions[position_id]
        if position.status == PositionStatus.CLOSED: return False

        current_price = await self._get_real_price(position.symbol)
        if not current_price: current_price = position.entry_price

        self.process_position_close(position, current_price, reason)
        return True
    def process_position_close(self, position: PaperPosition, close_price: Decimal, reason: str):
        """
        Внутренний метод для обработки полного закрытия paper-позиции.
        """
        if position.status == PositionStatus.CLOSED:
            return

        # Полностью закрываем позицию внутри ее объекта
        position.close_full(close_price, reason)

        # --- ИСПРАВЛЕНИЕ ---
        # Обновляем баланс: добавляем ТОЛЬКО чистый PnL
        pnl_to_report = position.realized_pnl
        self.current_balance += pnl_to_report
        # --- КОНЕЦ ИСПРАВЛЕНИЯ ---

        if self.risk_manager:
            position_size = position.original_size  # Исходная маржа
            self.risk_manager.register_position_close(
                position_size=position_size,
                pnl=pnl_to_report,  # <-- Также исправлено
                current_balance=self.current_balance  # Передаем обновленный баланс
            )
            logging.info(f"🛡️ RiskManager updated for paper trade. New paper balance: {self.current_balance:.2f}")

        # Логгируем в историю
        self._log_trade_to_history(position, close_price, reason)

    def _log_trade_to_history(self, position: PaperPosition, exit_price: Decimal, reason: str):
        trade_result = {
            'symbol': position.symbol, 'side': position.direction,
            'entry': float(position.entry_price), 'exit': float(exit_price),
            'pnl': float(position.realized_pnl), 'reason': reason,
            'open_time': position.timestamp.isoformat(),
            'close_time': datetime.now(timezone.utc).isoformat()
        }
        self.paper_trades_history.append(trade_result)

        # ✅ ДОБАВЛЕНО: Регистрация сделки в дневной статистике
        try:
            if hasattr(self.bot, 'daily_stats') and self.bot.daily_stats:
                self.bot.daily_stats.add_trade(
                    channel_id=position.channel_id,
                    channel_name=position.channel_name,
                    symbol=position.symbol,
                    side=position.direction,
                    pnl=float(position.realized_pnl),
                    entry=float(position.entry_price),
                    exit=float(exit_price)
                )
                logging.info(f"📊 Сделка добавлена в дневную статистику: {position.channel_name}")
        except Exception as e:
            logging.error(f"⚠️ Ошибка при добавлении сделки в daily_stats: {e}")


    def get_statistics(self) -> Dict:
        open_positions = self.get_open_positions()
        total_pnl = sum(t['pnl'] for t in self.paper_trades_history)
        unrealized_pnl = sum(p.get('pnl', 0) for p in open_positions)

        
        current_balance_with_pnl = self.current_balance + Decimal(str(unrealized_pnl))
        risk_report = {}
        if self.risk_manager:
            # Передаем баланс с учетом нереализованного PnL для расчета просадки
            risk_report = self.risk_manager.get_risk_report(current_balance_with_pnl)

        return {
            'enabled': self.enabled,
            'total_trades': len(self.paper_trades_history),
            'current_balance': float(current_balance_with_pnl),
            'start_balance': float(self.start_balance),
            'total_pnl': round(total_pnl, 2),
            'open_positions': len(open_positions),
            'risk_report': risk_report
        }
    def get_open_positions(self) -> List[Dict]:
        positions_list = []
        for pos in self.paper_positions.values():
            if pos.status != PositionStatus.CLOSED:
                pos_dict = pos.to_dict()
                mock_price = self.bot.get_enhanced_mock_price(pos.symbol, pos.entry_price)
                unrealized_pnl = pos.get_unrealized_pnl(mock_price)
                pnl_percent = (unrealized_pnl / pos.original_size) * 100 / pos.leverage if pos.original_size > 0 else 0
                pos_dict['pnl'] = float(unrealized_pnl)
                pos_dict['pnl_percent'] = float(pnl_percent)
                positions_list.append(pos_dict)
        return positions_list

    # --- ✅ НАЧАЛО НЕДОСТАЮЩЕГО КОДА ---
    def save_state(self, filename: str = "paper_positions.json"):
        """Сохраняет открытые paper-позиции в файл."""
        try:
            # Собираем данные только для активных позиций
            open_positions_data = [pos.to_dict() for pos in self.paper_positions.values() if pos.status != PositionStatus.CLOSED]
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(open_positions_data, f, indent=2, default=str)
            logging.info(f"✅ Успешно сохранено {len(open_positions_data)} paper-позиций в {filename}")
        except Exception as e:
            logging.error(f"❌ Не удалось сохранить состояние Paper Trading: {e}")

    def load_state(self, filename: str = "paper_positions.json"):
        """Загружает paper-позиции из файла."""
        try:
            if not os.path.exists(filename):
                logging.info(f"Файл {filename} не найден, загрузка пропущена.")
                return

            with open(filename, 'r', encoding='utf-8') as f:
                positions_data = json.load(f)

            loaded_count = 0
            for data in positions_data:
                try:
                    # Воссоздаем объект PaperPosition из данных JSON
                    pos = PaperPosition(
                        symbol=data['symbol'],
                        entry_price=Decimal(str(data['entry'])),
                        direction=data['side'],
                        size=Decimal(str(data['margin'])),
                        sl=Decimal(str(data['sl'])) if data.get('sl') else None,
                        tp_levels=[{'price': Decimal(str(data['tp1'])), 'percent': self.bot.config.tp1_close_percent, 'number': 1, 'hit': data.get('tp1_hit', False)}],
                        leverage=data.get('leverage', 1),
                        channel_id=data.get('channel_id', 'unknown'),  # ✅ Добавить
                        channel_name=data.get('channel_name', 'Unknown Channel')  # ✅ Добавить
                    )
                    # Восстанавливаем остальные атрибуты
                    pos.id = data.get('id', f"paper_{data['symbol'].replace('/', '')}_{int(time.time())}")
                    pos.status = PositionStatus(data.get('status', 'open'))
                    pos.remaining_size = Decimal(str(data.get('remaining_amount', data['margin'])))
                    pos.timestamp = datetime.fromisoformat(data['timestamp']) if data.get('timestamp') else datetime.now(timezone.utc)
                    pos.trailing_stop.enabled = data.get('trailing_active', False)
                    if pos.trailing_stop.enabled and data.get('trailing_stop'):
                        pos.trailing_stop.current_level = Decimal(str(data['trailing_stop']['current_level']))

                    self.paper_positions[pos.id] = pos
                    loaded_count += 1
                except Exception as e:
                    logging.error(f"Ошибка при загрузке отдельной paper-позиции: {data.get('id')}. Ошибка: {e}")

            logging.info(f"✅ Успешно загружено {loaded_count} paper-позиций из {filename}")

        except json.JSONDecodeError as e:
            logging.error(f"❌ Ошибка декодирования JSON из файла {filename}: {e}")
        except Exception as e:
            logging.error(f"❌ Не удалось загрузить состояние Paper Trading: {e}\n{traceback.format_exc()}")
            self.paper_positions = {}
