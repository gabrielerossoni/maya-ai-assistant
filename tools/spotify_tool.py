"""
spotify_tool.py - Controllo Media di Sistema (Play/Pause, Next)
Poiché vogliamo una versione 'base', simuliamo i tasti multimediali di Windows per controllare Spotify o altri player.
"""
import keyboard
import webbrowser

class SpotifyTool:
    def initialize(self):
        pass

    def execute(self, action: dict) -> dict:
        command = action.get("command", "play_pause") # play_pause, next, prev, open
        
        try:
            if command == "open":
                webbrowser.open("spotify:")
                return {"status": "ok", "message": "Spotify aperto."}
            elif command == "play_pause":
                keyboard.send("play/pause media")
                return {"status": "ok", "message": "Play/Pausa inviato."}
            elif command == "next":
                keyboard.send("next track")
                return {"status": "ok", "message": "Brano successivo."}
            elif command == "prev":
                keyboard.send("previous track")
                return {"status": "ok", "message": "Brano precedente."}
            else:
                return {"status": "error", "message": f"Comando '{command}' non valido per Spotify."}
        except Exception as e:
            return {"status": "error", "message": str(e)}
