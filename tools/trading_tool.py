"""
trading_tool.py - Dati su Criptovalute e Azioni, con integrazione base TradingView
"""
import requests
import yfinance as yf
import webbrowser

class TradingTool:
    def initialize(self):
        pass

    def execute(self, action: dict) -> dict:
        operation = action.get("operation", "price") # price, chart
        symbol = action.get("symbol", "bitcoin")
        asset_type = action.get("asset_type", "crypto") # crypto, stock

        try:
            if operation == "chart":
                # Apre il grafico su TradingView
                tv_symbol = symbol.upper()
                if asset_type == "crypto":
                    tv_symbol = f"{tv_symbol}USD" # Approssimazione per TV
                url = f"https://www.tradingview.com/chart/?symbol={tv_symbol}"
                webbrowser.open(url)
                return {"status": "ok", "message": f"Aperto grafico di {tv_symbol} su TradingView."}

            elif operation == "price":
                if asset_type == "crypto":
                    # Usa CoinGecko API gratuita
                    url = f"https://api.coingecko.com/api/v3/simple/price?ids={symbol.lower()}&vs_currencies=usd"
                    res = requests.get(url).json()
                    if symbol.lower() in res:
                        price = res[symbol.lower()]["usd"]
                        return {"status": "ok", "message": f"Il prezzo di {symbol.capitalize()} è ${price:,.2f}."}
                    else:
                        return {"status": "error", "message": f"Criptovaluta '{symbol}' non trovata."}
                elif asset_type == "stock":
                    # Usa yfinance
                    ticker = yf.Ticker(symbol.upper())
                    data = ticker.history(period="1d")
                    if not data.empty:
                        price = data["Close"].iloc[-1]
                        return {"status": "ok", "message": f"Il prezzo delle azioni {symbol.upper()} è ${price:,.2f}."}
                    else:
                        return {"status": "error", "message": f"Ticker azionario '{symbol}' non trovato."}
            else:
                return {"status": "error", "message": "Operazione trading non valida."}

        except Exception as e:
            return {"status": "error", "message": str(e)}
