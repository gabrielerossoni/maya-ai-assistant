from unittest.mock import MagicMock

from tools.trading_tool import TradingTool


def test_trading_tool_maps_btc_alias_to_bitcoin(monkeypatch):
    mock_response = MagicMock()
    mock_response.json.return_value = {"bitcoin": {"usd": 100000, "usd_24h_change": 1.25}}
    mock_get = MagicMock(return_value=mock_response)
    monkeypatch.setattr("tools.trading_tool.requests.get", mock_get)

    result = TradingTool().execute({"operation": "price", "symbol": "btc"})

    assert result["status"] == "ok"
    assert result["data"]["symbol"] == "BTC"
    assert result["data"]["coin_id"] == "bitcoin"
    assert "ids=bitcoin" in mock_get.call_args.args[0]


def test_trading_tool_keeps_short_stock_tickers_as_stock(monkeypatch):
    hist = MagicMock()
    hist.empty = False
    hist.__len__.return_value = 2
    hist.__getitem__.return_value.iloc.__getitem__.side_effect = [100.0, 110.0]
    ticker = MagicMock()
    ticker.history.return_value = hist
    monkeypatch.setattr("tools.trading_tool.yf.Ticker", MagicMock(return_value=ticker))

    result = TradingTool().execute({"operation": "price", "symbol": "spy"})

    assert result["status"] == "ok"
    assert result["data"]["asset_type"] == "stock"
