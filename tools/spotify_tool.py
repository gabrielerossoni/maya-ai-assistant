"""
spotify_tool.py - Controllo Spotify tramite Web API (spotipy)
"""

import os
import spotipy
from spotipy.oauth2 import SpotifyOAuth

SCOPE = " ".join([
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "user-read-private",
])

class SpotifyTool:
    def __init__(self):
        self.sp: spotipy.Spotify | None = None
        self.current_device_id: str | None = None

    def initialize(self):
        try:
            auth_manager = SpotifyOAuth(
                client_id=os.getenv("SPOTIFY_CLIENT_ID"),
                client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
                redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI", "http://localhost:8888/callback"),
                scope=SCOPE,
                cache_path="data/.spotify_token_cache",
                open_browser=True,
            )
            self.sp = spotipy.Spotify(auth_manager=auth_manager)
            user = self.sp.current_user()
            print(f"[SPOTIFY] Connesso come: {user['display_name']}")
        except Exception as e:
            print(f"[SPOTIFY] Errore init: {e}")
            self.sp = None

    def execute(self, action: dict) -> dict:
        if not self.sp:
            return {"status": "error", "message": "Spotify non connesso."}

        command = action.get("command", "current")

        try:
            if command == "play_pause":
                return self._toggle_play_pause()
            elif command == "play":
                self.sp.start_playback(device_id=self.current_device_id)
                return {"status": "ok", "message": "Play."}
            elif command == "pause":
                self.sp.pause_playback(device_id=self.current_device_id)
                return {"status": "ok", "message": "Pausa."}
            elif command == "next":
                self.sp.next_track()
                return {"status": "ok", "message": "Brano successivo."}
            elif command == "prev":
                self.sp.previous_track()
                return {"status": "ok", "message": "Brano precedente."}
            elif command == "volume":
                level = int(action.get("level", 50))
                return self._set_volume(max(0, min(100, level)))
            elif command == "volume_up":
                return self._adjust_volume(+10)
            elif command == "volume_down":
                return self._adjust_volume(-10)
            elif command == "current":
                return self._current_track()
            elif command == "search":
                return self._search_and_play(action.get("query", ""))
            elif command == "devices":
                return self._list_devices()
            elif command == "set_device":
                device_id = action.get("device_id", "")
                return self._set_device(device_id)
            elif command == "set_device_pc":
                return self._set_device_pc()
            else:
                return {"status": "error", "message": f"Comando '{command}' non riconosciuto."}

        except spotipy.exceptions.SpotifyException as e:
            if e.http_status == 403:
                return {"status": "error", "message": "Nessun dispositivo Spotify attivo. Apri Spotify sul PC o telefono."}
            if e.http_status == 401:
                return {"status": "error", "message": "Token scaduto. Riavvia MAYA."}
            return {"status": "error", "message": str(e)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ── Helpers ───────────────────────────────────

    def _toggle_play_pause(self) -> dict:
        pb = self.sp.current_playback()
        if pb and pb.get("is_playing"):
            self.sp.pause_playback(device_id=self.current_device_id)
            return {"status": "ok", "message": "Pausa."}
        else:
            self.sp.start_playback(device_id=self.current_device_id)
            return {"status": "ok", "message": "Play."}

    def _set_volume(self, level: int) -> dict:
        try:
            self.sp.volume(level)
            return {"status": "ok", "message": f"Volume: {level}%"}
        except spotipy.exceptions.SpotifyException as e:
            if e.http_status == 403:
                # Fallback: tasti sistema
                try:
                    import keyboard
                    # Normalizza: 0-100 → n pressioni
                    current = self._get_current_volume()
                    diff = level - current
                    key = "volume up" if diff > 0 else "volume down"
                    for _ in range(abs(diff) // 5):
                        keyboard.send(key)
                    return {"status": "ok", "message": f"Volume (sistema): {level}%"}
                except Exception:
                    return {"status": "ok", "message": "Volume: dispositivo non controllabile via API."}
            raise

    def _get_current_volume(self) -> int:
        try:
            pb = self.sp.current_playback()
            return pb["device"]["volume_percent"] if pb else 50
        except Exception:
            return 50

    def _adjust_volume(self, delta: int) -> dict:
        current = self._get_current_volume()
        return self._set_volume(max(0, min(100, current + delta)))

    def _current_track(self) -> dict:
        track = self.sp.current_user_playing_track()
        if not track or not track.get("item"):
            return {"status": "ok", "message": "Nessun brano in riproduzione.", "track": "", "artist": "", "is_playing": False, "album_art": ""}
        item = track["item"]
        name = item["name"]
        artist = item["artists"][0]["name"]
        is_playing = track["is_playing"]
        # Album art: prendi la versione 300x300
        images = item.get("album", {}).get("images", [])
        album_art = images[1]["url"] if len(images) > 1 else (images[0]["url"] if images else "")
        stato = "▶" if is_playing else "⏸"
        return {
            "status": "ok",
            "message": f"{stato} {name} — {artist}",
            "track": name,
            "artist": artist,
            "is_playing": is_playing,
            "album_art": album_art,
        }

    def _search_and_play(self, query: str) -> dict:
        if not query:
            return {"status": "error", "message": "Query vuota."}
        results = self.sp.search(q=query, type="track", limit=1)
        tracks = results.get("tracks", {}).get("items", [])
        if not tracks:
            return {"status": "error", "message": f"Nessun brano trovato per '{query}'."}
        uri = tracks[0]["uri"]
        name = tracks[0]["name"]
        artist = tracks[0]["artists"][0]["name"]
        self.sp.start_playback(uris=[uri], device_id=self.current_device_id)
        return {"status": "ok", "message": f"▶ {name} — {artist}"}

    def _list_devices(self) -> dict:
        try:
            devices = self.sp.devices()
            device_list = devices.get("devices", [])
            if not device_list:
                return {"status": "ok", "message": "Nessun dispositivo trovato. Apri Spotify su un device."}
            
            msg = "Dispositivi disponibili:\n"
            for dev in device_list:
                icon = "💻" if dev["type"] == "Computer" else "📱" if dev["type"] == "Smartphone" else "🔊"
                status = "✓ Attivo" if dev.get("is_active") else "○"
                msg += f"{icon} {dev['name']} ({dev['type']}) {status}\n"
            
            return {"status": "ok", "message": msg.strip(), "devices": device_list}
        except Exception as e:
            return {"status": "error", "message": f"Errore nel leggere dispositivi: {e}"}

    def _set_device(self, device_id: str) -> dict:
        try:
            if not device_id:
                return {"status": "error", "message": "Device ID non fornito."}
            
            devices = self.sp.devices()
            device_list = devices.get("devices", [])
            matching_device = next((d for d in device_list if d["id"] == device_id), None)
            
            if not matching_device:
                return {"status": "error", "message": "Dispositivo non trovato."}
            
            self.current_device_id = device_id
            return {"status": "ok", "message": f"Dispositivo selezionato: {matching_device['name']}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _set_device_pc(self) -> dict:
        try:
            devices = self.sp.devices()
            device_list = devices.get("devices", [])
            
            # Cerca il primo dispositivo Computer
            pc_device = next((d for d in device_list if d["type"] == "Computer"), None)
            
            if not pc_device:
                return {"status": "error", "message": "Nessun PC trovato. Apri Spotify Desktop su questo computer."}
            
            self.current_device_id = pc_device["id"]
            return {"status": "ok", "message": f"✓ PC selezionato: {pc_device['name']}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}