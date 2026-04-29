import os
import sys
import time
import threading
import queue
import numpy as np
import pyaudio
import wave
import subprocess
import asyncio
from faster_whisper import WhisperModel
import openwakeword
from openwakeword.model import Model

class VoiceManager:
    def __init__(self, agent, socket_manager=None):
        self.agent = agent
        self.socket_manager = socket_manager
        self.is_running = False
        self.is_listening = False
        self.is_speaking = False
        
        # Parametri Audio
        self.FORMAT = pyaudio.paInt16
        self.CHANNELS = 1
        self.RATE = 16000
        self.CHUNK = 1280 # 80ms per openwakeword
        
        # Code per la comunicazione tra thread
        self.audio_queue = queue.Queue()
        
        # Inizializzazione Modelli (Lazy loading per non bloccare l'avvio)
        self.stt_model = None
        self.oww_model = None
        
        # Path per Piper (assumiamo siano in voice/)
        self.piper_exe = os.path.join("voice", "piper.exe")
        self.piper_model = os.path.join("voice", "it_IT-paola-medium.onnx")
        
    def _initialize_models(self):
        print("[VOICE] Caricamento modelli vocali...")
        # STT: faster-whisper (tiny per velocità estrema)
        self.stt_model = WhisperModel("tiny", device="cpu", compute_type="int8")
        
        # Wake Word: Cerchiamo il modello personalizzato 'hey_maya.onnx'
        custom_ww = os.path.join("voice", "hey_maya.onnx")
        if os.path.exists(custom_ww):
            self.oww_model = Model(wakeword_models=[custom_ww], inference_framework="onnx")
            print(f"[VOICE] Wake Word personalizzata caricata: {custom_ww}")
        else:
            # Fallback se non esiste ancora
            self.oww_model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
            print("[VOICE] Modello 'hey_maya.onnx' non trovato. Uso fallback 'hey_jarvis'.")
        
        print("[VOICE] Modelli caricati con successo.")

    async def broadcast_status(self, status):
        if self.socket_manager:
            await self.socket_manager.broadcast({
                "type": "voice_status",
                "status": status
            })

    def start(self):
        self.is_running = True
        self._initialize_models()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        print("[VOICE] Sistema vocale avviato e in ascolto.")

    def _run_loop(self):
        try:
            audio = pyaudio.PyAudio()
            stream = audio.open(format=self.FORMAT, channels=self.CHANNELS,
                                rate=self.RATE, input=True,
                                frames_per_buffer=self.CHUNK)
            
            print("[VOICE] In attesa della Wake Word 'Hey Maya'...")
            
            while self.is_running:
                data = stream.read(self.CHUNK, exception_on_overflow=False)
                audio_data = np.frombuffer(data, dtype=np.int16)
                
                # 1. Controllo Wake Word
                prediction = self.oww_model.predict(audio_data)
                
                # Soglia abbassata a 0.3 per aumentare la sensibilità
                if any(prediction[mdl] > 0.3 for mdl in prediction):
                    score = max(prediction[mdl] for mdl in prediction)
                    print(f"[VOICE] Wake Word rilevata! (score: {score:.2f})")
                    if self.agent.loop:
                        asyncio.run_coroutine_threadsafe(self.broadcast_status("LISTENING"), self.agent.loop)
                    self._handle_voice_command(stream)
                    
            stream.stop_stream()
            stream.close()
            audio.terminate()
        except Exception as e:
            print(f"[VOICE] ERRORE CRITICO nel loop vocale: {e}")
            self.is_running = False

    def _handle_voice_command(self, stream):
        import asyncio
        self.is_listening = True
        print("[VOICE] Ascolto in corso...")
        
        # Registra per 5 secondi (semplificazione, poi aggiungeremo VAD)
        frames = []
        for _ in range(0, int(self.RATE / self.CHUNK * 5)):
            data = stream.read(self.CHUNK, exception_on_overflow=False)
            frames.append(data)
            
        self.is_listening = False
        print("[VOICE] Elaborazione comando...")
        
        # Converti in wav temporaneo per Whisper
        temp_wav = "voice/temp_command.wav"
        wf = wave.open(temp_wav, 'wb')
        wf.setnchannels(self.CHANNELS)
        wf.setsampwidth(pyaudio.PyAudio().get_sample_size(self.FORMAT))
        wf.setframerate(self.RATE)
        wf.writeframes(b''.join(frames))
        wf.close()
        
        # 2. Trascrizione (STT)
        segments, _ = self.stt_model.transcribe(temp_wav, beam_size=5)
        text = " ".join([segment.text for segment in segments]).strip()
        
        if text:
            print(f"[VOICE] Trascrizione: {text}")
            asyncio.run_coroutine_threadsafe(self.broadcast_status("PROCESSING"), self.agent.loop)
            
            # 3. Processa con l'agente
            response = asyncio.run_coroutine_threadsafe(self.agent.process(text), self.agent.loop).result()
            
            # 4. Parla (TTS)
            self.speak(response)
        else:
            print("[VOICE] Nessun comando rilevato.")

    def speak(self, text):
        if not os.path.exists(self.piper_exe):
            print(f"[VOICE] ERRORE: Piper non trovato in {self.piper_exe}")
            return
            
        print(f"[VOICE] Sintesi vocale: {text}")
        self.is_speaking = True
        if self.agent.loop:
            asyncio.run_coroutine_threadsafe(self.broadcast_status("SPEAKING"), self.agent.loop)
        
        try:
            output_wav = "voice/response.wav"
            # Comando per Piper: passa il testo e genera il wav
            command = f'echo {text} | "{self.piper_exe}" --model "{self.piper_model}" --output_file {output_wav}'
            subprocess.run(command, shell=True, check=True)
            
            # Riproduzione controllata via PyAudio (evita loop e lettori esterni)
            self._play_wav(output_wav)
            
        except Exception as e:
            print(f"[VOICE] Errore TTS: {e}")
            
        self.is_speaking = False
        if self.agent.loop:
            asyncio.run_coroutine_threadsafe(self.broadcast_status("IDLE"), self.agent.loop)

    def _play_wav(self, file_path):
        """Riproduce un file WAV usando PyAudio in modo sincrono."""
        try:
            wf = wave.open(file_path, 'rb')
            p = pyaudio.PyAudio()
            stream = p.open(format=p.get_format_from_width(wf.getsampwidth()),
                            channels=wf.getnchannels(),
                            rate=wf.getframerate(),
                            output=True)
            
            data = wf.readframes(self.CHUNK)
            while data:
                stream.write(data)
                data = wf.readframes(self.CHUNK)
            
            stream.stop_stream()
            stream.close()
            p.terminate()
        except Exception as e:
            print(f"[VOICE] Errore riproduzione audio: {e}")

if __name__ == "__main__":
    # Test stub
    pass
