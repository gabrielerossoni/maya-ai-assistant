#!/usr/bin/env python3
"""
Test del DashboardLogFilter per verificare il corretto filtraggio dei log.
"""

import sys
import asyncio
from log_utils import DashboardLogFilter

class MockWebSocketManager:
    """Mock di manager per testare il broadcast dei messaggi."""
    def __init__(self):
        self.messages = []
    
    async def broadcast(self, message: dict):
        self.messages.append(message)
        print(f"  [BROADCAST] {message['text']} (level: {message['level']})")

async def test_log_filter():
    """Test del filtro log."""
    print("=" * 60)
    print("TEST: DashboardLogFilter")
    print("=" * 60)
    
    manager = MockWebSocketManager()
    
    # Salva stdout originale
    original_stdout = sys.stdout
    
    # Crea il filtro
    filter_obj = DashboardLogFilter(original_stdout, manager)
    sys.stdout = filter_obj
    
    # Test 1: Richiesta dell'utente
    print("\n--- Test 1: Richiesta dell'utente ---")
    print("Richiesta: accendi la luce")
    await asyncio.sleep(0.1)
    
    # Test 2: Risposta di MAYA
    print("\n--- Test 2: Risposta di MAYA ---")
    print("MAYA > Ho acceso la luce del soggiorno!")
    await asyncio.sleep(0.1)
    
    # Test 3: Log tecnico (NON dovrebbe essere inviato alla dashboard)
    print("\n--- Test 3: Log tecnico (NON dovrebbe essere inviato) ---")
    print("[SYSTEM] Inizializzazione completata")
    print("[AGENT] Tool manager pronto")
    await asyncio.sleep(0.1)
    
    # Test 4: Errore critico
    print("\n--- Test 4: Errore critico (dovrebbe essere inviato) ---")
    print("[ERRORE] Connessione a Ollama fallita")
    await asyncio.sleep(0.1)
    
    # Test 5: Nucleo connesso
    print("\n--- Test 5: Messaggio di connessione ---")
    print("Nucleo Maya Connesso")
    await asyncio.sleep(0.1)
    
    # Ripristina stdout
    sys.stdout = original_stdout
    
    # Risultati
    print("\n" + "=" * 60)
    print("RISULTATI DEL TEST")
    print("=" * 60)
    print(f"Messaggi inviati alla dashboard: {len(manager.messages)}")
    print("\nDettagli messaggi:")
    for i, msg in enumerate(manager.messages, 1):
        print(f"  {i}. {msg['text']} (level: {msg['level']})")
    
    print("\n" + "=" * 60)
    print("RIEPILOGO ATTESO:")
    print("  - Test 1: ✓ Richiesta inviata")
    print("  - Test 2: ✓ Risposta MAYA inviata")
    print("  - Test 3: ✗ Log tecnici NON inviati (0 messaggi)")
    print("  - Test 4: ✓ Errore critico inviato")
    print("  - Test 5: ✓ Messaggio di connessione inviato")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_log_filter())
