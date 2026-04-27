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
])

class SpotifyTool:
    def __init__(self):
        self.sp: spotipy.Spotify | None = None

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
                self.sp.start_playback()
                return {"status": "ok", "message": "Play."}
            elif command == "pause":
                self.sp.pause_playback()
                return {"status": "ok", "message": "Pausa."}
            elif command == "next":
                self.sp.next_track()
                return {"status": "ok", "message": "Brano successivo."}
            elif command == "prev":
                self.sp.previous_track()
                return {"status": "ok", "message": "Brano precedente."}
            elif command == "volume_up":
                return self._adjust_volume(+10)
            elif command == "volume_down":
                return self._adjust_volume(-10)
            elif command == "volume":
                level = int(action.get("level", 50))
                self.sp.volume(max(0, min(100, level)))
                return {"status": "ok", "message": f"Volume: {level}%."}
            elif command == "current":
                return self._current_track()
            elif command == "search":
                return self._search_and_play(action.get("query", ""))
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
            self.sp.pause_playback()
            return {"status": "ok", "message": "Pausa."}
        else:
            self.sp.start_playback()
            return {"status": "ok", "message": "Play."}

    def _adjust_volume(self, delta: int) -> dict:
        pb = self.sp.current_playback()
        if not pb:
            return {"status": "error", "message": "Nessuna riproduzione attiva."}
        new_vol = max(0, min(100, pb["device"]["volume_percent"] + delta))
        self.sp.volume(new_vol)
        return {"status": "ok", "message": f"Volume: {new_vol}%"}

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
        self.sp.start_playback(uris=[uri])
        return {"status": "ok", "message": f"▶ {name} — {artist}"}