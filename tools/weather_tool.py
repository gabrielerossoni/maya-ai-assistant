"""
weather_tool.py - API meteo via Open-Meteo
"""
import requests
import os

class WeatherTool:
    def initialize(self):
        pass

    WMO_CODES = {
        0: ("Sereno", "sun"),
        1: ("Preval. Sereno", "cloud-sun"),
        2: ("Parzialm. Nuvoloso", "cloud-sun"),
        3: ("Nuvoloso", "cloud"),
        45: ("Nebbia", "cloud-fog"),
        48: ("Nebbia Brillante", "cloud-fog"),
        51: ("Pioggerellina", "cloud-drizzle"),
        61: ("Pioggia Leggera", "cloud-rain"),
        63: ("Pioggia", "cloud-rain"),
        71: ("Neve Leggera", "cloud-snow"),
        95: ("Temporale", "cloud-lightning")
    }

    def execute(self, action: dict) -> dict:
        location = action.get("location") or os.getenv("DEFAULT_WEATHER_LOCATION")
        if not location:
            return {"status": "error", "message": "Località non specificata. Fornire 'location' o impostare 'DEFAULT_WEATHER_LOCATION'."}
        # Primo step: Geocoding
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={location}&count=1&language=it&format=json"
        try:
            geo_res = requests.get(geo_url).json()
            if "results" not in geo_res or len(geo_res["results"]) == 0:
                return {"status": "error", "message": f"Località '{location}' non trovata."}
            
            res0 = geo_res["results"][0]
            lat, lon, name = res0["latitude"], res0["longitude"], res0["name"]

            # Secondo step: Meteo + Previsioni
            weather_url = (
                f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                "&current_weather=true&daily=temperature_2m_max,temperature_2m_min,weathercode"
                "&timezone=auto"
            )
            w_res = requests.get(weather_url).json()
            current = w_res.get("current_weather", {})
            daily = w_res.get("daily", {})
            
            code = current.get("weathercode")
            condition, icon = self.WMO_CODES.get(code, ("Variabile", "cloud-sun"))
            
            data = {
                "location": name,
                "temp": current.get("temperature"),
                "wind": current.get("windspeed"),
                "code": code,
                "condition": condition,
                "icon": icon,
                "daily": []
            }

            # Prepara previsioni per i prossimi 5 giorni
            for i in range(1, 6):
                day_code = daily.get("weathercode")[i]
                day_cond, day_icon = self.WMO_CODES.get(day_code, ("Variabile", "cloud-sun"))
                data["daily"].append({
                    "date": daily.get("time")[i],
                    "max": daily.get("temperature_2m_max")[i],
                    "min": daily.get("temperature_2m_min")[i],
                    "code": day_code,
                    "condition": day_cond,
                    "icon": day_icon
                })

            return {"status": "ok", "message": f"Meteo a {name}: {data['temp']}°C", "data": data}
        except Exception as e:
            return {"status": "error", "message": str(e)}
