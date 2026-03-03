from api.http import register_http_routes
from api.websocket import register_ws


class WebInterface:
    """
    Связывает FastAPI <-> TradingBot
    """

    def __init__(self, app, bot):
        self.app = app
        self.bot = bot

        register_http_routes(app, bot)
        register_ws(app)
