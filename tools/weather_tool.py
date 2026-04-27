"""
weather_tool.py - API meteo via Open-Meteo
"""
import requests
import os

class WeatherTool:
    def initialize(self):
        pass

    def execute(self, action: dict) -> dict:
        location = action.get("location", os.getenv("DEFAULT_WEATHER_LOCATION", "Roma"))
        # Primo step: Geocoding per ottenere lat/lon
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={location}&count=1&language=it&format=json"
        try:
            geo_res = requests.get(geo_url).json()
            if "results" not in geo_res or len(geo_res["results"]) == 0:
                return {"status": "error", "message": f"Località '{location}' non trovata."}
            
            lat = geo_res["results"][0]["latitude"]
            lon = geo_res["results"][0]["longitude"]
            name = geo_res["results"][0]["name"]

            # Secondo step: Recupero meteo
            weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
            w_res = requests.get(weather_url).json()
            current = w_res.get("current_weather", {})
            temp = current.get("temperature", "N/A")
            wind = current.get("windspeed", "N/A")

            msg = f"A {name} ci sono {temp}°C con vento a {wind} km/h."
            return {"status": "ok", "message": msg}
        except Exception as e:
            return {"status": "error", "message": str(e)}
