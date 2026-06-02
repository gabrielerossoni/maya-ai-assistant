from __future__ import annotations

import asyncio
import os
import queue
import re
import subprocess
import sys
import threading
import time
import wave

# Su Windows, aggiunge i percorsi delle DLL di nvidia (cublas e cudnn) se installate via pip
if sys.platform == "win32":
    import site

    for site_pkg in site.getsitepackages():
        for lib in ["cublas", "cudnn"]:
            bin_path = os.path.join(site_pkg, "nvidia", lib, "bin")
            if os.path.isdir(bin_path):
                try:
                    os.add_dll_directory(bin_path)
                except Exception:
                    pass

import numpy as np
import pyaudio
from faster_whisper import WhisperModel

# Regex precompilati una tantum per wake phrase strip
_MAYA = r"(?:maya|maia|maja|máya|màya)"
_GREET = r"(?:ehi|ehy|hey|ei|hi|eh|ehì|e')"

_PAT_CLEAN_BRACKETS = re.compile(r"(?is)^\[[^\]]*\]\s*")
_PAT_CLEAN_PARENS = re.compile(r"(?is)^\([^)]{0,48}\)\s*")

_PAT_GREET = re.compile(rf"(?is){_GREET}\s*,?\s*{_MAYA}\b\s*[,:\-]?\s*")
_PAT_E_MAYA = re.compile(rf"(?is)^e\s*,?\s*{_MAYA}\b\s*[,:\-]?\s*")
_PAT_EH_MAYA = re.compile(rf"(?is)^eh\s*,?\s*{_MAYA}\b\s*[,:\-]?\s*")
_PAT_OK_MAYA = re.compile(rf"(?is)^(ok|okay|oké)\s*,?\s*{_MAYA}\b\s*[,:\-]?\s*")
_PAT_MAYA = re.compile(rf"(?is)^{_MAYA}\b\s*[,:\-]?\s*")


class VoiceManager:
    def __init__(self, agent, socket_manager=None):
        self.agent = agent
        self.socket_manager = socket_manager
        self.is_running = False
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

    def _initialize_models(self):
        # STT: faster-whisper (small per accuratezza italiano)
        model_size = os.environ.get("MAYA_WHISPER_MODEL", "large-v3-turbo")
        try:
            # Caricamento silenzioso su GPU (CUDA)
            self.stt_model = WhisperModel(model_size, device="cuda", compute_type="float16")
            self._stt_device = "cuda"
            # Test rapido per verificare che cuBLAS sia funzionante
            # (il modello si carica, ma cuBLAS potrebbe fallire alla prima inferenza)
            import numpy as _np

            _test = _np.zeros(16000, dtype=_np.float32)
            list(self.stt_model.transcribe(_test, language="it", beam_size=1, vad_filter=False)[0])
        except Exception as e:
            err_msg = str(e)
            if "cublas" in err_msg.lower() or "cuda" in err_msg.lower():
                print(f"[VOICE] CUDA/cuBLAS non disponibile ({err_msg}). Fallback su CPU...")
                print("[VOICE] Per risolvere: installa CUDA Toolkit 12.x o imposta MAYA_WHISPER_DEVICE=cpu")
            else:
                print(f"[VOICE] GPU non disponibile ({e}). Uso della CPU in corso...")
            try:
                self.stt_model = WhisperModel(model_size, device="cpu", compute_type="int8")
                self._stt_device = "cpu"
                print(f"[VOICE] Whisper caricato su CPU (modello: {model_size})")
            except Exception as e_cpu:
                print(f"[VOICE] Errore critico durante il caricamento di Whisper su CPU: {e_cpu}")

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
        t = _PAT_CLEAN_BRACKETS.sub("", t)
        t = _PAT_CLEAN_PARENS.sub("", t)

        m = _PAT_GREET.search(t)
        if m:
            return t[m.end() :].strip()

        m_e = _PAT_E_MAYA.match(t)
        if m_e:
            return t[m_e.end() :].strip()

        m_eh = _PAT_EH_MAYA.match(t)
        if m_eh:
            return t[m_eh.end() :].strip()

        m_ok = _PAT_OK_MAYA.match(t)
        if m_ok:
            return t[m_ok.end() :].strip()

        m2 = _PAT_MAYA.match(t)
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
            await self.socket_manager.broadcast({"type": "voice_status", "status": status})

    def _voice_event_loop(self):
        """Stesso loop di uvicorn: preferisci manager.loop (impostato nel lifespan)."""
        if self.socket_manager and getattr(self.socket_manager, "loop", None):
            return self.socket_manager.loop
        return getattr(self.agent, "loop", None)

    def _broadcast(self, status: str):
        """Accoda lo stato voce sul loop principale (thread-safe)."""
        self._dashboard_voice_status = status.strip().upper() if isinstance(status, str) else "IDLE"
        # Attendi che il loop sia pronto (timeout per non bloccare il thread vocale all'infinito)
        if not self._loop_ready.is_set():
            if not self._loop_ready.wait(timeout=2.0):
                print(f"[VOICE] Avviso: Loop non pronto, broadcast '{status}' ignorato.")
                return

        loop = self._voice_event_loop()
        if not loop:
            return
        try:
            fut = asyncio.run_coroutine_threadsafe(self.broadcast_status(self._dashboard_voice_status), loop)

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
            stream = audio.open(
                format=self.FORMAT, channels=self.CHANNELS, rate=self.RATE, input=True, frames_per_buffer=self.CHUNK
            )

            self._calibrate_vad_from_stream(stream)

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
                    self._broadcast("IDLE")
                    continue

                # LISTENING è già emesso dentro _record_utterance_*; dopo wake + comando inline va in PROCESSING
                if cmd:
                    # _process_voice_text è async, dobbiamo schedularlo nel loop corretto
                    loop = self._voice_event_loop()
                    if loop:
                        asyncio.run_coroutine_threadsafe(self._process_voice_text(cmd), loop)
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
        w = self.followup_wait_sec

        pcm = self._record_utterance_pcm(stream, max_leading_silence_sec=w)

        if not pcm:
            self._broadcast("IDLE")
            return

        if len(pcm) < self.CHUNK * self.followup_min_chunks:
            self._broadcast("IDLE")
            return

        self._broadcast("TRANSCRIBING")
        try:
            text = self._transcribe_pcm(pcm)
        except Exception as e:
            print(f"[VOICE] Errore trascrizione comando: {e}")
            self._broadcast("IDLE")
            return
        if not text:
            self._broadcast("IDLE")
            return

        stripped = self._strip_wake_phrase(text)
        if stripped is not None:
            cmd_text = stripped
        else:
            cmd_text = text

        if not cmd_text.strip():
            self._broadcast("IDLE")
            return

        # _process_voice_text è async, dobbiamo schedularlo nel loop corretto
        loop = self._voice_event_loop()
        if loop:
            asyncio.run_coroutine_threadsafe(self._process_voice_text(cmd_text.strip()), loop)

    def _split_sentences(self, text: str) -> list[str]:
        """Divide il testo in frasi complete (separatori: . ! ? e a-capo con elenco)."""
        parts = re.split(r"(?<=[.!?])\s+|\n[-*]\s*|\n{2,}", text)
        return [p.strip().lstrip("-").lstrip("*").strip() for p in parts if p.strip()]

    async def _process_voice_text(self, text: str):
        self._broadcast("PROCESSING")
        # Mostra il testo trascritto sulla dashboard
        if self.socket_manager:
            await self.socket_manager.broadcast({"type": "stream", "token": f"🎤 {text}\n", "full_text": f"🎤 {text}"})
        print(f"Richiesta (voce): {text}")
        try:
            is_news_request = any(word in text.lower() for word in ["notizie", "news", "notiziario", "aggiornamenti"])

            # ── Streaming TTS: parla frase per frase mentre l'agente genera ──
            sentence_buf = ""
            full_reply = ""
            spoke_something = False
            spoken_sentences: set[str] = set()

            # Coda per frasi pronte → thread TTS le riproduce in pipeline
            tts_queue: queue.Queue = queue.Queue()
            tts_done = threading.Event()

            def _tts_worker():
                """Thread dedicato: riproduce frasi dalla coda appena disponibili."""
                first = True
                while True:
                    sentence = tts_queue.get()
                    if sentence is None:  # sentinella di fine
                        break
                    if first:
                        self.is_speaking = True
                        first = False
                    normalized = re.sub(r"\s+", " ", sentence.strip().lower())
                    if normalized and normalized not in spoken_sentences:
                        spoken_sentences.add(normalized)
                        self._speak_raw(sentence)
                    if is_news_request:
                        time.sleep(0.8)
                tts_done.set()

            tts_thread = threading.Thread(target=_tts_worker, daemon=True)
            tts_thread.start()

            try:
                async for token in self.agent.process(text):
                    full_reply += token
                    sentence_buf += token

                    # Controlla se abbiamo una frase completa nel buffer
                    sentences = self._split_sentences(sentence_buf)
                    if len(sentences) > 1:
                        # Tutte tranne l'ultima (potrebbe essere incompleta)
                        for s in sentences[:-1]:
                            if s:
                                tts_queue.put(s)
                                spoke_something = True
                        sentence_buf = sentences[-1]
            except asyncio.TimeoutError:
                print("[VOICE] Timeout agente: risposta parziale.")
            except Exception as e:
                print(f"[VOICE] Errore stream agente: {e}")

            # Frase residua nel buffer
            remainder = sentence_buf.strip()
            if remainder:
                tts_queue.put(remainder)
                spoke_something = True

            # Segnala fine coda
            tts_queue.put(None)
            tts_done.wait(timeout=30)

            # Recupera dati finali (layout) salvati dall'agente
            layout_data = {"type": "orb", "params": {}}
            task = asyncio.current_task()
            if task and task in self.agent._current_task_final_data:
                _, layout_data = self.agent._current_task_final_data.pop(task)
            elif hasattr(self.agent, "_last_final_data"):
                _, layout_data = self.agent._last_final_data

            if full_reply.strip() and self.socket_manager:
                await self.socket_manager.broadcast(
                    {
                        "type": "layout",
                        "layout": layout_data.get("type", "orb"),
                        "params": layout_data.get("params", {}),
                    }
                )

            if not spoke_something:
                print("[VOICE] Risposta agente vuota, niente TTS.")

        except Exception as e:
            print(f"[VOICE] Errore durante l'elaborazione: {e}")
            import traceback

            traceback.print_exc()
        finally:
            self.is_speaking = False
            self._broadcast("IDLE")

    def _speak_raw(self, text: str):
        """Sintetizza e riproduce una singola frase (usato dal TTS pipeline worker)."""
        if not os.path.exists(self.piper_exe):
            return
        try:
            import uuid

            os.makedirs("voice", exist_ok=True)
            output_wav = f"voice/response_{uuid.uuid4().hex}.wav"
            command = [self.piper_exe, "--model", self.piper_model, "--output_file", output_wav]
            subprocess.run(
                command, input=text.encode("utf-8"), check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            self._broadcast("SPEAKING")
            self._play_wav(output_wav)
        except Exception as e:
            print(f"[VOICE] Errore TTS raw: {e}")
        finally:
            if not self.is_speaking:
                self._broadcast("IDLE")

    def speak(self, text):
        if not os.path.exists(self.piper_exe):
            print(f"[VOICE] ERRORE: Piper non trovato in {self.piper_exe}")
            self._broadcast("IDLE")
            return

        self.is_speaking = True
        self._broadcast("SPEAKING")

        try:
            import uuid

            os.makedirs("voice", exist_ok=True)
            output_wav = f"voice/response_{uuid.uuid4().hex}.wav"
            # Comando per Piper: passa il testo e genera il wav
            command = [self.piper_exe, "--model", self.piper_model, "--output_file", output_wav]
            subprocess.run(
                command, input=text.encode("utf-8"), check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )

            # Riproduzione controllata via PyAudio (niente lettore multimediale)
            self._play_wav(output_wav)

        except Exception as e:
            print(f"[VOICE] Errore TTS: {e}")
        finally:
            self.is_speaking = False
            self._broadcast("IDLE")

    def _play_wav(self, file_path):
        """Riproduce un file WAV usando PyAudio in modo sincrono e controllato."""
        try:
            wf = wave.open(file_path, "rb")
            p = pyaudio.PyAudio()
            stream = p.open(
                format=p.get_format_from_width(wf.getsampwidth()),
                channels=wf.getnchannels(),
                rate=wf.getframerate(),
                output=True,
            )

            chunk_size = 4096
            data = wf.readframes(chunk_size)
            while len(data) > 0:
                stream.write(data)
                data = wf.readframes(chunk_size)

            stream.stop_stream()
            stream.close()
            wf.close()
            p.terminate()

            # Cancella il file WAV temporaneo dopo la riproduzione per evitare accumulo su disco
            if "voice/response_" in file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass
        except Exception as e:
            print(f"[VOICE] Errore riproduzione audio: {e}")

    def stop(self):
        self.is_running = False
        if hasattr(self, "thread"):
            self.thread.join(timeout=2)
        print("[VOICE] Sistema vocale fermato.")


if __name__ == "__main__":
    # Test stub
    pass
