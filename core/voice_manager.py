import os
import sys
import time
import threading
import queue
import re
import numpy as np
import pyaudio
import wave
import subprocess
import asyncio
from faster_whisper import WhisperModel

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
        self.CHUNK = 1280  # 80 ms @ 16 kHz
        
        # Code per la comunicazione tra thread
        self.audio_queue = queue.Queue()
        
        # Inizializzazione Modelli (Lazy loading per non bloccare l'avvio)
        self.stt_model = None
        
        # Path per Piper (assumiamo siano in voice/)
        self.piper_exe = os.path.join("voice", "piper.exe")
        self.piper_model = os.path.join("voice", "it_IT-paola-medium.onnx")

        # Fallback statico se MAYA_DISABLE_ADAPTIVE_VAD=1 (o calibrazione saltata).
        # speech deve stare sopra silence di un margine chiaro (~60+).
        self.speech_rms_threshold = float(os.environ.get("MAYA_SPEECH_RMS", "235"))
        self.silence_rms_threshold = float(os.environ.get("MAYA_SILENCE_RMS", "160"))
        self.silence_chunks_for_end = int(os.environ.get("MAYA_SILENCE_CHUNKS", "18"))
        self.max_utterance_sec = float(os.environ.get("MAYA_MAX_UTTERANCE_SEC", "14"))
        # Wake breve: default basso così «Ehy Maya» non viene scartata per durata (voci gravi più corte sul mic)
        self.min_utterance_chunks = int(os.environ.get("MAYA_MIN_UTTERANCE_CHUNKS", "6"))
        self._vad_speech: float | None = None
        self._vad_silence: float | None = None
        self._noise_floor: float | None = None
        self.whisper_language = os.environ.get("MAYA_WHISPER_LANGUAGE", "it")
        self.followup_wait_sec = float(os.environ.get("MAYA_FOLLOWUP_WAIT_SEC", "22"))
        self.followup_min_chunks = int(
            os.environ.get(
                "MAYA_FOLLOWUP_MIN_CHUNKS",
                str(max(5, self.min_utterance_chunks - 3)),
            )
        )
        # Ultimo stato inviato / da mostrare in dashboard (sincrono su reconnect e stats).
        self._dashboard_voice_status: str = "IDLE"
        self._loop_ready = threading.Event()

    def set_loop_ready(self):
        """Segnala che il loop è pronto per i broadcast."""
        self._loop_ready.set()
        print("[VOICE] Loop di sistema pronto per i broadcast.")

    def _initialize_models(self):
        print("[VOICE] Caricamento modelli vocali...")
        # STT: faster-whisper (tiny per velocità estrema)
        self.stt_model = WhisperModel("tiny", device="cpu", compute_type="int8")
        print("[VOICE] Attivazione con frase tipo «Ehi Maya» (Whisper + VAD RMS adattivo).")
        print(
            f"[VOICE] Fallback statico: RMS voce≥{self.speech_rms_threshold:.0f}, "
            f"silenzio<{self.silence_rms_threshold:.0f}, min chunk={self.min_utterance_chunks} "
            "(sovrascrivi con MAYA_*; MAYA_DISABLE_ADAPTIVE_VAD=1 usa solo queste)."
        )
        print("[VOICE] Modelli caricati con successo.")

    def get_dashboard_voice_status(self) -> str:
        """Stato voce da propagare sulla dashboard (WebSocket reconnect / piggyback)."""
        return self._dashboard_voice_status

    def voice_status_message(self) -> dict:
        return {"type": "voice_status", "status": self._dashboard_voice_status}

    def _rms_thresholds(self) -> tuple[float, float]:
        """Soglie effettive: calibrate se presenti, altrimenti da env/default."""
        if self._vad_speech is not None and self._vad_silence is not None:
            return self._vad_speech, self._vad_silence
        return self.speech_rms_threshold, self.silence_rms_threshold

    def _calibrate_vad_from_stream(self, stream) -> None:
        """Stima rumore ambiente e imposta soglie relativistiche (migliora voci gravi / mic deboli)."""
        disabled = os.environ.get("MAYA_DISABLE_ADAPTIVE_VAD", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        if disabled:
            self._vad_speech = self.speech_rms_threshold
            self._vad_silence = self.silence_rms_threshold
            print("[VOICE] VAD adattivo disabilitato (solo soglie MAYA_SPEECH_RMS / MAYA_SILENCE_RMS).")
            return

        self._broadcast("CALIBRATING")
        n = int(os.environ.get("MAYA_CALIB_CHUNKS", "36"))
        print("[VOICE] Calibrazione rumore (~3 s): meglio ambiente tranquillo davanti al microfono.")
        chunks: list[float] = []
        for _ in range(max(12, n)):
            if not self.is_running:
                return
            data = stream.read(self.CHUNK, exception_on_overflow=False)
            chunks.append(self._pcm_rms(np.frombuffer(data, dtype=np.int16)))

        arr = np.array(chunks, dtype=np.float64)
        # Percentili robusti se l'utente tossisce una volta nella finestra
        noise = float(min(np.percentile(arr, 12), np.percentile(arr, 38)))

        above_s = float(os.environ.get("MAYA_ADAPTIVE_SPEECH_DELTA", "78"))
        above_i = float(os.environ.get("MAYA_ADAPTIVE_SILENCE_DELTA", "32"))
        gap = float(os.environ.get("MAYA_ADAPTIVE_MIN_GAP", "52"))

        speech = noise + above_s
        silence = noise + above_i
        if speech - silence < gap:
            silence = speech - gap
        silence = max(silence, noise + 12.0)

        smin = float(os.environ.get("MAYA_SPEECH_RMS_MIN", "88"))
        smax = float(os.environ.get("MAYA_SPEECH_RMS_MAX", "540"))
        imin = float(os.environ.get("MAYA_SILENCE_RMS_MIN", "42"))

        speech = max(smin, min(speech, smax))
        silence = max(imin, min(silence, speech - 36.0))

        self._noise_floor = noise
        self._vad_speech = speech
        self._vad_silence = silence
        print(
            f"[VOICE] VAD effettivo: fondo rumore≈{noise:.0f} "
            f"→ soglia parlato≥{speech:.0f}, fine frase quando RMS<{silence:.0f} "
            f"per ~{self.silence_chunks_for_end * (self.CHUNK / self.RATE):.1f}s"
        )

    @staticmethod
    def _pcm_rms(audio_int16: np.ndarray) -> float:
        if audio_int16.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(audio_int16.astype(np.float64) ** 2)))

    def _strip_wake_phrase(self, text: str) -> str | None:
        """Dopo saluto+maya: resto del testo (anche ''). Solo maya iniziale: resto. Altrimenti None."""
        if not text or not text.strip():
            return None
        t = text.strip()
        t = re.sub(r"(?is)^\[[^\]]*\]\s*", "", t)
        t = re.sub(r"(?is)^\([^)]{0,48}\)\s*", "", t)

        maya = r"(?:maya|maia|maja|máya|màya)"
        greet = r"(?:ehi|ehy|hey|ei|hi|eh|ehì|e')"
        pat_greet = re.compile(rf"(?is){greet}\s*,?\s*{maya}\b\s*[,:\-]?\s*")
        m = pat_greet.search(t)
        if m:
            return t[m.end() :].strip()

        # Whisper spesso abbrevia «Ehi» → «E» prima di Maya
        pat_e_maya = re.compile(rf"(?is)^e\s*,?\s*{maya}\b\s*[,:\-]?\s*")
        m_e = pat_e_maya.match(t)
        if m_e:
            return t[m_e.end() :].strip()

        pat_eh_maya = re.compile(rf"(?is)^eh\s*,?\s*{maya}\b\s*[,:\-]?\s*")
        m_eh = pat_eh_maya.match(t)
        if m_eh:
            return t[m_eh.end() :].strip()

        pat_ok_maya = re.compile(rf"(?is)^(ok|okay|oké)\s*,?\s*{maya}\b\s*[,:\-]?\s*")
        m_ok = pat_ok_maya.match(t)
        if m_ok:
            return t[m_ok.end() :].strip()

        pat_maya = re.compile(rf"(?is)^{maya}\b\s*[,:\-]?\s*")
        m2 = pat_maya.match(t)
        if m2:
            return t[m2.end() :].strip()

        return None

    def _record_utterance_pcm(
        self,
        stream,
        *,
        max_leading_silence_sec: float | None = None,
    ) -> bytes | None:
        """Attende voce, registra fino a silenzio o limite di durata.

        Se max_leading_silence_sec è impostato, dopo così tanti secondi senza parlato
        ritorna None (timeout). Default None = attende indefinitamente (loop principale).

        LISTENING solo dopo che il RMS supera la soglia parlato: così tra un turno e l'altro
        non restiamo sempre «in ascolto» in dashboard mentre il mic è in attesa silenziosa.
        """
        frames: list[bytes] = []
        max_leading_chunks: int | None = None
        if max_leading_silence_sec is not None:
            max_leading_chunks = max(1, int(max_leading_silence_sec * self.RATE / self.CHUNK))

        th_speech, th_silence = self._rms_thresholds()
        leading_quiet = 0
        while self.is_running:
            data = stream.read(self.CHUNK, exception_on_overflow=False)
            a = np.frombuffer(data, dtype=np.int16)
            if self._pcm_rms(a) >= th_speech:
                self._broadcast("LISTENING")
                frames.append(data)
                break
            if max_leading_chunks is not None:
                leading_quiet += 1
                if leading_quiet >= max_leading_chunks:
                    return None

        if not self.is_running or not frames:
            return None

        silent_chunks = 0
        max_chunks = int(self.RATE / self.CHUNK * self.max_utterance_sec)
        while self.is_running and len(frames) < max_chunks:
            data = stream.read(self.CHUNK, exception_on_overflow=False)
            frames.append(data)
            a = np.frombuffer(data, dtype=np.int16)
            if self._pcm_rms(a) < th_silence:
                silent_chunks += 1
                if silent_chunks >= self.silence_chunks_for_end:
                    break
            else:
                silent_chunks = 0
        return b"".join(frames)

    def _transcribe_pcm(self, pcm: bytes) -> str:
        """Trascrive PCM int16 16kHz mono senza file WAV: evita errori FFmpeg su temp_command.wav."""
        if len(pcm) < 4:
            return ""
        n_samples = len(pcm) // 2
        if n_samples < 320:
            return ""
        audio_i16 = np.frombuffer(pcm[: n_samples * 2], dtype=np.int16).copy()
        audio_f32 = (audio_i16.astype(np.float32) / 32768.0).clip(-1.0, 1.0)

        lang = self.whisper_language.strip() or None
        # vad_filter=False: non tagliare l’inizio/fine piani (fundamentali per voci gravi)
        segments, _ = self.stt_model.transcribe(
            audio_f32,
            beam_size=5,
            language=lang,
            vad_filter=False,
        )
        return " ".join(segment.text for segment in segments).strip()

    async def broadcast_status(self, status):
        if self.socket_manager:
            await self.socket_manager.broadcast({
                "type": "voice_status",
                "status": status
            })

    def _voice_event_loop(self):
        """Stesso loop di uvicorn: preferisci manager.loop (impostato nel lifespan)."""
        if self.socket_manager and getattr(self.socket_manager, "loop", None):
            return self.socket_manager.loop
        return getattr(self.agent, "loop", None)

    def _broadcast(self, status: str):
        """Accoda lo stato voce sul loop principale (thread-safe)."""
        self._dashboard_voice_status = (
            status.strip().upper() if isinstance(status, str) else "IDLE"
        )
        # Attendi che il loop sia pronto (timeout per non bloccare il thread vocale all'infinito)
        if not self._loop_ready.is_set():
            if not self._loop_ready.wait(timeout=2.0):
                print(f"[VOICE] Avviso: Loop non pronto, broadcast '{status}' ignorato.")
                return

        loop = self._voice_event_loop()
        if not loop:
            return
        try:
            fut = asyncio.run_coroutine_threadsafe(
                self.broadcast_status(self._dashboard_voice_status), loop
            )

            def _log_err(f):
                try:
                    f.result()
                except Exception as e:
                    sv = getattr(self, "_dashboard_voice_status", status)
                    print(f"[VOICE] Invio stato '{sv}' alla dashboard fallito: {e}")

            fut.add_done_callback(_log_err)
        except Exception as e:
            print(f"[VOICE] _broadcast scheduling fallito: {e}")

    def start(self):
        self.is_running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        print("[VOICE] Thread vocale avviato (caricamento modelli in background).")

    def _run_loop(self):
        try:
            try:
                self._initialize_models()
            except Exception as e:
                print(f"[VOICE] Caricamento modelli fallito: {e}")
                import traceback
                traceback.print_exc()
                self.is_running = False
                return

            audio = pyaudio.PyAudio()
            stream = audio.open(format=self.FORMAT, channels=self.CHANNELS,
                                rate=self.RATE, input=True,
                                frames_per_buffer=self.CHUNK)

            self._calibrate_vad_from_stream(stream)

            print("[VOICE] Microfono pronto: di' «Ehi Maya» e poi il comando.")
            self._broadcast("IDLE")

            while self.is_running:
                pcm = self._record_utterance_pcm(stream)
                if not pcm or not self.is_running:
                    self._broadcast("IDLE")
                    continue
                if len(pcm) < self.CHUNK * self.min_utterance_chunks:
                    self._broadcast("IDLE")
                    continue

                self._broadcast("TRANSCRIBING")
                try:
                    text = self._transcribe_pcm(pcm)
                except Exception as e:
                    print(f"[VOICE] Errore trascrizione: {e}")
                    self._broadcast("IDLE")
                    continue

                if not text:
                    self._broadcast("IDLE")
                    continue

                cmd = self._strip_wake_phrase(text)
                if cmd is None:
                    if os.environ.get("MAYA_VOICE_DEBUG"):
                        print(f"[VOICE] (debug) Ignorato, nessuna wake phrase in: {text!r}")
                    else:
                        print(
                            "[VOICE] Trascrizione senza wake (serve «Ehi Maya»… o «Maya» in testa): "
                            f"{text!r}"
                        )
                    self._broadcast("IDLE")
                    continue

                print(f"[VOICE] Attivazione riconosciuta. Trascrizione: {text!r}")

                # LISTENING è già emesso dentro _record_utterance_*; dopo wake + comando inline va in PROCESSING
                if cmd:
                    self._process_voice_text(cmd)
                else:
                    self._handle_voice_command(stream)

                self._broadcast("IDLE")
                    
            stream.stop_stream()
            stream.close()
            audio.terminate()
        except Exception as e:
            print(f"[VOICE] ERRORE CRITICO nel loop vocale: {e}")
            import traceback
            traceback.print_exc()
            self.is_running = False

    def _handle_voice_command(self, stream):
        """Dopo solo «Ehi Maya»: attendi che l'utente inizi a parlare, poi registra fino alla pausa."""
        self.is_listening = True
        w = self.followup_wait_sec
        print(
            f"[VOICE] Dimmi il comando quando vuoi (hai ~{w:.0f} s per iniziare, poi parla e fai una pausa)."
        )

        pcm = self._record_utterance_pcm(stream, max_leading_silence_sec=w)
        self.is_listening = False

        if not pcm:
            print("[VOICE] Timeout: non ho sentito il comando.")
            self._broadcast("IDLE")
            return

        if len(pcm) < self.CHUNK * self.followup_min_chunks:
            print("[VOICE] Audio troppo breve dopo l'attivazione, ignoro.")
            self._broadcast("IDLE")
            return

        print("[VOICE] Elaborazione comando...")
        self._broadcast("TRANSCRIBING")
        try:
            text = self._transcribe_pcm(pcm)
        except Exception as e:
            print(f"[VOICE] Errore trascrizione comando: {e}")
            self._broadcast("IDLE")
            return
        if not text:
            print("[VOICE] Nessun comando rilevato.")
            self._broadcast("IDLE")
            return

        stripped = self._strip_wake_phrase(text)
        if stripped is not None:
            cmd_text = stripped
        else:
            cmd_text = text

        if not cmd_text.strip():
            print("[VOICE] Nessun comando dopo l'attivazione (solo wake phrase?).")
            self._broadcast("IDLE")
            return

        print(f"[VOICE] Trascrizione: {cmd_text}")
        self._process_voice_text(cmd_text.strip())

    def _process_voice_text(self, text: str):
        loop = self._voice_event_loop()
        if loop is None:
            print("[VOICE] Nessun asyncio loop (agent/manager.loop): comando vocale ignorato.")
            self._broadcast("IDLE")
            return
        self._broadcast("PROCESSING")
        try:
            response = asyncio.run_coroutine_threadsafe(
                self.agent.process(text),
                loop,
            ).result(timeout=180)
            if response and str(response).strip():
                self.speak(response)
            else:
                print("[VOICE] Risposta agente vuota, niente TTS.")
        except Exception as e:
            print(f"[VOICE] Errore durante l'elaborazione: {e}")
            self._broadcast("IDLE")

    def speak(self, text):
        if not os.path.exists(self.piper_exe):
            print(f"[VOICE] ERRORE: Piper non trovato in {self.piper_exe}")
            self._broadcast("IDLE")
            return
            
        print(f"[VOICE] Sintesi vocale: {text[:80]}...")
        self.is_speaking = True
        self._broadcast("SPEAKING")
        
        try:
            output_wav = "voice/response.wav"
            # Comando per Piper: passa il testo e genera il wav
            # Fix shell injection: use list of args and pass text via input
            command = [
                self.piper_exe,
                "--model", self.piper_model,
                "--output_file", output_wav
            ]
            subprocess.run(
                command,
                input=text.encode('utf-8'),
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            # Riproduzione controllata via PyAudio (niente lettore multimediale)
            self._play_wav(output_wav)
            
        except Exception as e:
            print(f"[VOICE] Errore TTS: {e}")

        self.is_speaking = False

    def _play_wav(self, file_path):
        """Riproduce un file WAV usando PyAudio in modo sincrono e controllato."""
        try:
            wf = wave.open(file_path, 'rb')
            p = pyaudio.PyAudio()
            stream = p.open(format=p.get_format_from_width(wf.getsampwidth()),
                            channels=wf.getnchannels(),
                            rate=wf.getframerate(),
                            output=True)
            
            chunk_size = 4096
            data = wf.readframes(chunk_size)
            while len(data) > 0:
                stream.write(data)
                data = wf.readframes(chunk_size)
            
            stream.stop_stream()
            stream.close()
            wf.close()
            p.terminate()
        except Exception as e:
            print(f"[VOICE] Errore riproduzione audio: {e}")

    def stop(self):
        self.is_running = False
        if hasattr(self, 'thread'):
            self.thread.join(timeout=2)
        print("[VOICE] Sistema vocale fermato.")

if __name__ == "__main__":
    # Test stub
    pass
