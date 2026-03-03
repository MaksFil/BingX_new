import asyncio
import logging
import traceback
from decimal import Decimal
from typing import Optional, Dict, List

from utils.signal_parser import Signal
from core.safety.risk_manager import RiskManager, RiskLimits
from api.websocket_manager import websocket_manager
from api.bingx_client import BingXFuturesClient


class VSTTradingMode:
    """
    Advanced VST Trading Mode for BingX Demo Account.
    Supports:
    - Hedge Mode
    - Partial TP
    - RiskManager
    - Auto Sync
    - SL/TP on exchange side
    """

    def __init__(self, bot):
        self.bot = bot
        self.enabled = False
        self.client: Optional[BingXFuturesClient] = None
        self.risk_manager: Optional[RiskManager] = None
        self.hedge_mode = True
        self.sync_task = None

    # ==========================================================
    # ENABLE / DISABLE
    # ==========================================================

    def enable(self):
        try:
            self.client = BingXFuturesClient(
                api_key=self.bot.config.bingx_api_key,
                secret_key=self.bot.config.bingx_secret_key,
                is_vst=True
            )

            self.risk_manager = RiskManager(
                initial_balance=Decimal("10000"),
                limits=RiskLimits()
            )

            self.enabled = True
            self.sync_task = asyncio.create_task(self.auto_sync())

            logging.info("🟢 VST MODE ENABLED (BingX Demo)")
        except Exception as e:
            logging.error(f"❌ Failed to enable VST mode: {e}")

    def disable(self):
        self.enabled = False
        if self.sync_task:
            self.sync_task.cancel()
        self.client = None
        self.risk_manager = None
        logging.info("🔴 VST MODE DISABLED")

    # ==========================================================
    # OPEN POSITION
    # ==========================================================

    async def open_position(self, signal: Signal) -> Optional[str]:
        if not self.enabled or not self.client:
            return None

        try:
            margin = self.bot.config.trade_amount

            balance = Decimal(await self.client.get_balance())

            if self.risk_manager:
                can_open, msg = self.risk_manager.can_open_position(margin, balance)
                if not can_open:
                    await websocket_manager.notify("Risk Check Failed", msg, "warning")
                    return None

            side = "BUY" if signal.side.upper() == "BUY" else "SELL"

            # Set leverage
            if signal.leverage:
                await self.client.set_leverage(signal.symbol, signal.leverage)

            # Hedge mode support
            position_side = "LONG" if side == "BUY" else "SHORT" if self.hedge_mode else None

            # Place entry order
            order = await self.client.place_market_order(
                symbol=signal.symbol,
                side=side,
                margin=margin,
                leverage=signal.leverage,
                position_side=position_side
            )

            if not order:
                return None

            order_id = order.get("orderId")

            # Setup SL
            if signal.sl:
                await self.client.set_stop_loss(
                    symbol=signal.symbol,
                    stop_price=signal.sl,
                    position_side=position_side
                )

            # Setup Partial TP
            await self._setup_partial_tp(signal, margin, position_side)

            logging.info(f"✅ VST Position Opened: {signal.symbol}")
            return order_id

        except Exception as e:
            logging.error(f"❌ VST open_position error: {e}\n{traceback.format_exc()}")
            return None

    # ==========================================================
    # PARTIAL TP LOGIC
    # ==========================================================

    async def _setup_partial_tp(self, signal: Signal, margin: Decimal, position_side: str):
        tp_levels = []

        if hasattr(signal, "tp1") and signal.tp1:
            tp_levels.append((signal.tp1, self.bot.config.tp1_close_percent))

        if hasattr(signal, "tp2") and signal.tp2:
            tp_levels.append((signal.tp2, 50))

        if hasattr(signal, "tp3") and signal.tp3:
            tp_levels.append((signal.tp3, 100))

        for price, percent in tp_levels:
            await self.client.set_take_profit(
                symbol=signal.symbol,
                take_profit_price=price,
                percent=percent,
                position_side=position_side
            )

    # ==========================================================
    # CLOSE POSITION
    # ==========================================================

    async def close_position(self, symbol: str):
        if not self.enabled or not self.client:
            return False

        try:
            positions = await self.client.get_all_positions()

            for pos in positions:
                if pos["symbol"] == symbol and Decimal(pos["size"]) > 0:

                    close_side = "SELL" if pos["side"] == "LONG" else "BUY"

                    await self.client.place_market_order(
                        symbol=symbol,
                        side=close_side,
                        quantity=pos["size"],
                        position_side=pos["side"]
                    )

            logging.info(f"🔒 VST Position Closed: {symbol}")
            return True

        except Exception as e:
            logging.error(f"❌ VST close_position error: {e}")
            return False

    # ==========================================================
    # AUTO SYNC
    # ==========================================================

    async def auto_sync(self):
        while self.enabled:
            try:
                positions = await self.client.get_all_positions()
                await websocket_manager.broadcast({
                    "type": "vst_positions_update",
                    "positions": positions
                })
            except Exception as e:
                logging.error(f"❌ VST auto_sync error: {e}")

            await asyncio.sleep(5)

    # ==========================================================
    # TRAILING STOP (EXCHANGE SIDE)
    # ==========================================================

    async def activate_trailing_stop(self, symbol: str, callback_rate: Decimal):
        if not self.enabled:
            return

        try:
            await self.client.set_trailing_stop(
                symbol=symbol,
                callback_rate=callback_rate
            )
            logging.info(f"📈 Trailing activated for {symbol}")
        except Exception as e:
            logging.error(f"❌ Trailing error: {e}")
    
    # ==========================================================
    # UNIVERSAL CREATE ORDER (CCXT-like)
    # ==========================================================

    async def create_order(
        self,
        symbol: str,
        type: str,
        side: str,
        amount: float,
        price: float = None,
        params: Dict = None
    ) -> Optional[Dict]:
        """
        Универсальный метод создания ордера (аналог CCXT).
        Поддерживает market / limit.
        Работает в VST режиме через BingX.
        """

        if not self.enabled or not self.client:
            logging.warning("VST not enabled")
            return None

        try:
            params = params or {}
            side = side.upper()
            order_type = type.upper()

            # Hedge mode support
            position_side = None
            if self.hedge_mode:
                if side == "BUY":
                    position_side = "LONG"
                elif side == "SELL":
                    position_side = "SHORT"

            # --- MARKET ORDER ---
            if order_type == "MARKET":
                order = await self.client.place_market_order(
                    symbol=symbol,
                    side=side,
                    quantity=amount,
                    position_side=position_side
                )

            # --- LIMIT ORDER ---
            elif order_type == "LIMIT":
                if not price:
                    raise ValueError("LIMIT order requires price")

                order = await self.client.place_limit_order(
                    symbol=symbol,
                    side=side,
                    quantity=amount,
                    price=price,
                    position_side=position_side
                )
            else:
                raise ValueError(f"Unsupported order type: {type}")

            if not order:
                return None

            logging.info(
                f"📌 VST Order Created | {symbol} | {side} | {amount} | ID: {order.get('orderId')}"
            )

            return {
                "id": order.get("orderId"),
                "symbol": symbol,
                "type": order_type.lower(),
                "side": side.lower(),
                "amount": amount,
                "price": price,
                "info": order
            }

        except Exception as e:
            logging.error(f"❌ VST create_order error: {e}\n{traceback.format_exc()}")
            return None
        
    # ==========================================================
    # STATISTICS
    # ==========================================================

    async def get_statistics(self) -> Dict:
        if not self.enabled or not self.client:
            return {}

        try:
            balance = Decimal(await self.client.get_balance())
            positions = await self.client.get_all_positions()

            total_unrealized = sum(
                Decimal(p["unrealizedPnl"]) for p in positions
            )

            return {
                "enabled": True,
                "balance": float(balance),
                "open_positions": len(positions),
                "unrealized_pnl": float(total_unrealized),
                "positions": positions
            }

        except Exception as e:
            logging.error(f"❌ VST stats error: {e}")
            return {}