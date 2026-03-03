import logging
from decimal import Decimal
from fastapi import HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from api.telegram_auth import TelegramAuthManager

from models.api import (
    TradingConfigUpdateRequest,
    ClosePositionRequest,
)
from core.modes.traiding_mode import TradingMode

from api.dashboard import (
    get_dashboard_template,
    get_statistics_template,
    get_telegram_template,
)

from utils.cache import _global_caches

telegram_auth = TelegramAuthManager()

def register_http_routes(app, bot):

    # ==========================================================
    # HTML PAGES
    # ==========================================================

    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        return get_dashboard_template()

    @app.get("/statistics", response_class=HTMLResponse)
    async def statistics():
        return get_statistics_template()

    @app.get("/telegram", response_class=HTMLResponse)
    async def telegram():
        return get_telegram_template()

    # ==========================================================
    # SYSTEM INFO
    # ==========================================================

    @app.get("/api/cache_stats")
    async def get_cache_stats():
        if not _global_caches:
            return JSONResponse({"message": "No global caches found."})

        return JSONResponse(
            {k: v.get_stats() for k, v in _global_caches.items()}
        )

    @app.get("/api/error_stats")
    async def get_error_stats():
        return JSONResponse(
            bot.error_handler.get_error_stats(minutes=60)
        )

    # ==========================================================
    # POSITIONS
    # ==========================================================

    @app.get("/api/positions")
    async def get_positions():
        try:
            if bot.paper_trading and bot.paper_trading.enabled:
                return JSONResponse(
                    bot.paper_trading.get_open_positions()
                )

            return JSONResponse([
                {
                    "id": p.id,
                    "symbol": p.symbol,
                    "side": p.side,
                    "entry": float(p.entry),
                    "tp1": float(p.tp1) if p.tp1 else None,
                    "tp2": float(p.tp2) if getattr(p, "tp2", None) else None,
                    "sl": float(p.sl) if p.sl else None,
                    "margin": float(p.margin),
                    "pnl": float(p.pnl),
                    "status": p.status,
                }
                for p in bot.open_positions.values()
            ])

        except Exception as e:
            logging.error(e)
            raise HTTPException(500, str(e))

    # ==========================================================
    # TRADING CONFIG (NEW API)
    # ==========================================================

    @app.get("/api/trading-config")
    async def get_trading_config():
        return JSONResponse(bot.config.to_dict())

    @app.patch("/api/trading-config")
    async def update_trading_config(
        cfg: TradingConfigUpdateRequest
    ):
        try:
            data = cfg.dict(exclude_none=True)

            if not data:
                raise HTTPException(400, "No fields provided")

            # ---------------------------
            # VALIDATION
            # ---------------------------

            new_mode = data.get("mode", bot.config.mode)
            tp1 = data.get(
                "tp1_close_percent",
                bot.config.tp1_close_percent
            )
            tp2 = data.get(
                "tp2_close_percent",
                bot.config.tp2_close_percent
            )

            # CLASSIC → TP1 + TP2 = 100
            if new_mode == TradingMode.CLASSIC:
                if Decimal(tp1) + Decimal(tp2) != Decimal("100"):
                    raise HTTPException(
                        400,
                        "CLASSIC mode requires TP1 + TP2 = 100%"
                    )

            # Запрет смены режима если есть позиции
            if "mode" in data and bot.open_positions:
                raise HTTPException(
                    400,
                    "Cannot change trading mode while positions are open"
                )

            # ---------------------------
            # APPLY CONFIG
            # ---------------------------

            bot.config.update_from_dict(data)

            # ---------------------------
            # SAVE TO DB
            # ---------------------------

            for key, value in data.items():
                await bot.db_manager.save_config(
                    key,
                    str(value)
                )

            return JSONResponse({
                "status": "success",
                "updated_fields": list(data.keys()),
                "config": bot.config.to_dict()
            })

        except HTTPException:
            raise
        except Exception as e:
            logging.error(e)
            raise HTTPException(500, str(e))

    # ==========================================================
    # SET ONLY MODE (UI shortcut)
    # ==========================================================

    @app.post("/api/trading-mode/{mode}")
    async def set_trading_mode(mode: str):

        if mode not in [
            TradingMode.SAFETY,
            TradingMode.CLASSIC,
            TradingMode.PRO_TREND,
        ]:
            raise HTTPException(400, "Invalid mode")

        if bot.open_positions:
            raise HTTPException(
                400,
                "Cannot change trading mode while positions are open"
            )

        bot.config.mode = mode
        await bot.db_manager.save_config("mode", mode)

        return JSONResponse({
            "status": "success",
            "mode": mode
        })

    # ==========================================================
    # CLOSE POSITION
    # ==========================================================

    @app.post("/api/close_position")
    async def close_position(req: ClosePositionRequest):

        if bot.paper_trading and bot.paper_trading.enabled:
            ok = await bot.paper_trading.close_paper_position(
                req.position_id,
                "Manual Close"
            )
            if not ok:
                raise HTTPException(404, "Position not found")
        else:
            await bot.close_position_manual(
                req.position_id,
                "Manual close"
            )

        return JSONResponse({"status": "success"})

    # ==========================================================
    # UPDATE DEMO BALANCE
    # ==========================================================

    @app.post("/api/update_balance")
    async def update_balance(data: dict):

        if not bot.config.demo_mode:
            raise HTTPException(400, "Demo mode only")

        new_balance = Decimal(str(data["new_balance"]))

        return JSONResponse(
            await bot.update_demo_balance(new_balance)
        )
    
    # ==========================================================
    # TELEGRAM AUTH API
    # ==========================================================

    @app.post("/api/telegram/send_code")
    async def telegram_send_code(data: dict):
        try:
            result = await telegram_auth.send_code(
                api_id=int(data["api_id"]),
                api_hash=data["api_hash"],
                phone=data["phone"]
            )
            return JSONResponse(result)

        except Exception as e:
            raise HTTPException(400, str(e))


    @app.post("/api/telegram/verify")
    async def telegram_verify(data: dict):
        try:
            result = await telegram_auth.verify(
                code=data["code"],
                password=data.get("password")
            )
            return JSONResponse(result)

        except Exception as e:
            raise HTTPException(400, str(e))


    @app.get("/api/telegram/status")
    async def telegram_status():
        return JSONResponse(await telegram_auth.get_status())