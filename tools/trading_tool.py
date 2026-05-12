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
        # Estrai i parametri dalla chiave 'parametro' se presente (formato Planner)
        params = action.get("parametro", action)
        operation = params.get("operation", "price") # price, chart
        symbol = params.get("symbol", "bitcoin").lower()
        asset_type = params.get("asset_type") # Può essere None

        # Auto-detection dell'asset type se mancante
        if not asset_type:
            stock_indicators = ["spy", "aapl", "goog", "tsla", "msft", "amzn", "meta", "nvda", "sp500", "nasdaq"]
            if any(ind in symbol for ind in stock_indicators) or len(symbol) <= 5:
                # La maggior parte dei ticker stock sono brevi o in questa lista
                asset_type = "stock"
            else:
                asset_type = "crypto"

        try:
            if operation == "chart":
                # Apre il grafico su TradingView
                tv_symbol = symbol.upper()
                if asset_type == "crypto":
                    tv_symbol = f"{tv_symbol}USD"
                url = f"https://www.tradingview.com/chart/?symbol={tv_symbol}"
                webbrowser.open(url)
                return {"status": "ok", "message": f"Aperto grafico di {tv_symbol} su TradingView."}

            elif operation == "overview":
                items = []
                # CoinGecko — solo BTC e XRP
                try:
                    cg_url = (
                        "https://api.coingecko.com/api/v3/simple/price"
                        "?ids=bitcoin,ripple&vs_currencies=usd&include_24hr_change=true"
                    )
                    cg_res = requests.get(cg_url, timeout=10).json()
                    for cid, sym in [("bitcoin", "BTC"), ("ripple", "XRP")]:
                        if cid in cg_res:
                            p = cg_res[cid]["usd"]
                            chg = round(cg_res[cid].get("usd_24h_change", 0), 2)
                            items.append({
                                "symbol": sym, "price": p,
                                "price_str": f"${p:,.2f}",
                                "change_pct": chg, "asset_type": "crypto"
                            })
                except Exception:
                    pass

                # Yahoo Finance screener — top gainer e loser del giorno (universo intero)
                yf_headers = {"User-Agent": "Mozilla/5.0"}
                dynamic_tickers = set()
                try:
                    for scr_id in ["day_gainers", "day_losers"]:
                        url = (
                            f"https://query1.finance.yahoo.com/v1/finance/screener/"
                            f"predefined/saved?formatted=false&scrIds={scr_id}&count=8"
                            f"&region=US&lang=en-US"
                        )
                        r = requests.get(url, headers=yf_headers, timeout=8).json()
                        quotes = r.get("finance", {}).get("result", [{}])[0].get("quotes", [])
                        for q in quotes:
                            sym = q.get("symbol", "")
                            p = q.get("regularMarketPrice", 0)
                            chg = round(q.get("regularMarketChangePercent", 0), 2)
                            if sym and p and sym not in dynamic_tickers:
                                dynamic_tickers.add(sym)
                                items.append({
                                    "symbol": sym, "price": p,
                                    "price_str": f"${p:,.2f}",
                                    "change_pct": chg, "asset_type": "stock"
                                })
                except Exception:
                    pass

                # Anchor fissi — sempre presenti (se non già inclusi dallo screener)
                anchor_tickers = [t for t in ["SPY", "NVDA", "TSLA", "AAPL", "MSFT", "META"]
                                  if t not in dynamic_tickers]
                if anchor_tickers:
                    try:
                        raw = yf.download(
                            " ".join(anchor_tickers), period="5d",
                            progress=False, auto_adjust=True
                        )
                        closes = raw["Close"]
                        for t in anchor_tickers:
                            try:
                                col = closes[t] if hasattr(closes, 'columns') and t in closes.columns else closes
                                s = col.dropna()
                                if len(s) >= 2:
                                    prev, curr = float(s.iloc[-2]), float(s.iloc[-1])
                                    chg = round(((curr - prev) / prev) * 100, 2)
                                    items.append({
                                        "symbol": t, "price": curr,
                                        "price_str": f"${curr:,.2f}",
                                        "change_pct": chg, "asset_type": "stock"
                                    })
                            except Exception:
                                pass
                    except Exception:
                        pass

                # Ordina per change_pct decrescente, restituisce top 15
                items.sort(key=lambda x: x.get("change_pct", 0), reverse=True)
                return {"status": "ok", "data": {"items": items[:18], "overview": True}}

            elif operation == "price":
                if asset_type == "crypto":
                    url = (f"https://api.coingecko.com/api/v3/simple/price"
                           f"?ids={symbol.lower()}&vs_currencies=usd&include_24hr_change=true")
                    res = requests.get(url, timeout=10).json()
                    if symbol.lower() in res:
                        price = res[symbol.lower()]["usd"]
                        chg = round(res[symbol.lower()].get("usd_24h_change", 0), 2)
                        return {
                            "status": "ok",
                            "message": f"Il prezzo di {symbol.capitalize()} è ${price:,.2f} ({chg:+.2f}% 24h).",
                            "data": {"symbol": symbol, "price": price,
                                     "price_str": f"${price:,.2f}", "change_pct": chg, "asset_type": "crypto"}
                        }
                    else:
                        return {"status": "error", "message": f"Criptovaluta '{symbol}' non trovata."}
                elif asset_type == "stock":
                    hist = yf.Ticker(symbol.upper()).history(period="5d")
                    if not hist.empty:
                        curr = float(hist["Close"].iloc[-1])
                        chg = 0.0
                        if len(hist) >= 2:
                            prev = float(hist["Close"].iloc[-2])
                            chg = round(((curr - prev) / prev) * 100, 2)
                        return {
                            "status": "ok",
                            "message": f"Il prezzo di {symbol.upper()} è ${curr:,.2f} ({chg:+.2f}% 24h).",
                            "data": {"symbol": symbol, "price": curr,
                                     "price_str": f"${curr:,.2f}", "change_pct": chg, "asset_type": "stock"}
                        }
                    else:
                        return {"status": "error", "message": f"Ticker '{symbol}' non trovato."}
            else:
                return {"status": "error", "message": "Operazione trading non valida."}

        except Exception as e:
            return {"status": "error", "message": str(e)}
