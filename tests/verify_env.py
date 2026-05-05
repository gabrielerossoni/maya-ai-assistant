import os
import sys
from dotenv import load_dotenv

# Aggiungi la directory radice al path per importare agent_core
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_env_loading():
    load_dotenv()
    print("--- Verifica caricamento .env ---")
    vars_to_check = [
        "OLLAMA_HOST",
        "MODEL_ULTRA_FAST",
        "ARDUINO_PORT",
        "REMOTE_HOST",
        "DEFAULT_WEATHER_LOCATION",
        "NEWS_FEED_URL"
    ]
    
    for var in vars_to_check:
        val = os.getenv(var)
        print(f"{var}: {val}")
        if val is None:
            print(f"ERRORE: {var} non trovata!")
            return False
    
    print("\n--- Verifica AgentCore (import) ---")
    try:
        from core.agent_core import MODELS, SYSTEM_PROMPT
        print(f"MODELS: {MODELS}")
        # print(f"SYSTEM_PROMPT: {SYSTEM_PROMPT[:50]}...")
        print("AgentCore caricato correttamente.")
    except Exception as e:
        print(f"ERRORE in AgentCore: {e}")
        return False

    return True

if __name__ == "__main__":
    if test_env_loading():
        print("\nVerifica completata con SUCCESSO!")
    else:
        print("\nVerifica FALLITA!")
