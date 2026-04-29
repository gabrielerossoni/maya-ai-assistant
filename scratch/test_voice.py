import os
import subprocess

def test_tts():
    piper_exe = os.path.join("voice", "piper.exe")
    piper_model = os.path.join("voice", "it_IT-paola-medium.onnx")
    text = "Ciao, sono Maya, il tuo assistente vocale locale. Sono pronta a ricevere i tuoi comandi."
    output_wav = "voice/test_maya.wav"
    
    print(f"[TEST] Generazione audio con Piper...")
    # Usa echo per passare il testo a piper
    command = f'echo {text} | "{piper_exe}" --model "{piper_model}" --output_file {output_wav}'
    
    try:
        subprocess.run(command, shell=True, check=True)
        if os.path.exists(output_wav):
            print(f"[SUCCESS] File audio generato: {output_wav}")
            # Prova a riprodurlo (opzionale, non blocca il test)
            os.system(f"start /min {output_wav}")
        else:
            print("[ERROR] Il file audio non è stato generato.")
    except Exception as e:
        print(f"[ERROR] Errore durante il test TTS: {e}")

if __name__ == "__main__":
    test_tts()
