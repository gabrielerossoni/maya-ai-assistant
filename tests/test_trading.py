import sys
import os

# Aggiungi la root del progetto al path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.trading_tool import TradingTool

def test():
    tool = TradingTool()
    # Test S&P 500 (SPY) senza specificare asset_type (default crypto)
    res1 = tool.execute({"operation": "price", "symbol": "spy"})
    print(f"Test SPY (default): {res1}")
    
    # Test SPY specificando stock
    res2 = tool.execute({"operation": "price", "symbol": "spy", "asset_type": "stock"})
    print(f"Test SPY (stock): {res2}")

if __name__ == "__main__":
    test()
