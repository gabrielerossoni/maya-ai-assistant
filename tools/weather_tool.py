"""
weather_tool.py - API meteo via Open-Meteo
"""

import os

import requests


class WeatherTool:
    def __init__(self):
        self._cache = {}
        self.CACHE_EXPIRY = 300  # 5 minuti

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
        95: ("Temporale", "cloud-lightning"),
    }

    def execute(self, action: dict) -> dict:
        if not hasattr(self, "_cache"):
            self._cache = {}
            self.CACHE_EXPIRY = 300

        import time

        # Genera cache key basata sui parametri normalizzati
        cache_key = tuple(sorted((k, v) for k, v in action.items() if v is not None))
        now = time.time()
        if cache_key in self._cache:
            cached_data, cached_time = self._cache[cache_key]
            if now - cached_time < self.CACHE_EXPIRY:
                if cached_data.get("status") == "ok" and "data" in cached_data:
                    self._update_context_weather(cached_data["data"].get("icon"))
                return cached_data

        result = self._execute_uncached(action)
        if result.get("status") == "ok" and "data" in result:
            self._cache[cache_key] = (result, now)
            self._update_context_weather(result["data"].get("icon"))
        return result

    def _update_context_weather(self, icon: str | None):
        if not icon:
            return
        try:
            from core.context_manager import context

            icon_lower = icon.lower()
            ctx_weather = "unknown"
            if "rain" in icon_lower or "drizzle" in icon_lower or "lightning" in icon_lower:
                ctx_weather = "rain"
            elif "snow" in icon_lower:
                ctx_weather = "snow"
            elif "sun" in icon_lower:
                ctx_weather = "clear"
            elif "cloud" in icon_lower or "fog" in icon_lower:
                ctx_weather = "cloud"
            context.set_weather(ctx_weather)
        except Exception as e:
            print(f"[WEATHER] Errore aggiornamento contesto: {e}")

    def _execute_uncached(self, action: dict) -> dict:
        lat = action.get("lat")
        lon = action.get("lon")
        name = None

        if lat is not None and lon is not None:
            # Fallback name if Nominatim fails
            name = f"Lat {round(lat, 2)}, Lon {round(lon, 2)}"
            try:
                headers = {"User-Agent": "MAYA-AI-Assistant/1.0"}
                geo_url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=10"
                geo_res = requests.get(geo_url, headers=headers, timeout=3).json()
                address = geo_res.get("address", {})
                city = (
                    address.get("city")
                    or address.get("town")
                    or address.get("village")
                    or address.get("municipality")
                    or address.get("county")
                    or address.get("state")
                )
                if city:
                    name = city
                elif "display_name" in geo_res:
                    parts = geo_res["display_name"].split(",")
                    name = ", ".join(parts[:2]).strip()
            except Exception:
                pass
        else:
            location = action.get("location") or os.getenv("DEFAULT_WEATHER_LOCATION")
            if not location:
                return {
                    "status": "error",
                    "message": "Località non specificata. Fornire 'location' o impostare 'DEFAULT_WEATHER_LOCATION'.",
                }
            # Primo step: Geocoding
            geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={location}&count=1&language=it&format=json"
            try:
                geo_res = requests.get(geo_url, timeout=3).json()
                if "results" not in geo_res or len(geo_res["results"]) == 0:
                    return {"status": "error", "message": f"Località '{location}' non trovata."}

                res0 = geo_res["results"][0]
                lat, lon, name = res0["latitude"], res0["longitude"], res0["name"]
            except Exception as e:
                return {"status": "error", "message": f"Errore geocoding: {str(e)}"}

        # Secondo step: Meteo + Previsioni
        try:
            weather_url = (
                f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                "&current_weather=true"
                "&hourly=relativehumidity_2m,surface_pressure,visibility,precipitation,precipitation_probability,weathercode"
                "&daily=temperature_2m_max,temperature_2m_min,weathercode"
                "&timezone=auto"
            )
            w_res = requests.get(weather_url, timeout=4).json()
            current = w_res.get("current_weather", {})
            daily = w_res.get("daily", {})
            hourly = w_res.get("hourly", {})

            code = current.get("weathercode")
            condition, icon = self.WMO_CODES.get(code, ("Variabile", "cloud-sun"))

            # Prendi valori attuali da hourly (prima ora disponibile)
            humidity = hourly.get("relativehumidity_2m", [None])[0]
            pressure = hourly.get("surface_pressure", [None])[0]
            visibility_m = hourly.get("visibility", [None])[0]
            visibility_km = round(visibility_m / 1000, 1) if visibility_m else None

            data = {
                "location": name,
                "lat": lat,
                "lon": lon,
                "temp": current.get("temperature"),
                "wind": current.get("windspeed"),
                "humidity": humidity,
                "pressure": round(pressure) if pressure else None,
                "visibility": visibility_km,
                "code": code,
                "condition": condition,
                "icon": icon,
                "daily": [],
                "hourly": [],
            }

            # Prepara previsioni per i prossimi 5 giorni
            try:
                t_arr = daily.get("time") or []
                w_arr = daily.get("weathercode") or []
                mx = daily.get("temperature_2m_max") or []
                mn = daily.get("temperature_2m_min") or []
                n = min(len(t_arr), len(w_arr), len(mx), len(mn))
                for i in range(1, min(6, n)):
                    day_code = w_arr[i]
                    day_cond, day_icon = self.WMO_CODES.get(day_code, ("Variabile", "cloud-sun"))
                    data["daily"].append(
                        {
                            "date": t_arr[i],
                            "max": mx[i],
                            "min": mn[i],
                            "code": day_code,
                            "condition": day_cond,
                            "icon": day_icon,
                        }
                    )
            except Exception:
                pass

            # Prepara hourly compatto per le prossime ore
            try:
                h_time = hourly.get("time") or []
                h_prec = hourly.get("precipitation") or []
                h_prob = hourly.get("precipitation_probability") or []
                h_code = hourly.get("weathercode") or []
                n = min(len(h_time), len(h_prec), len(h_code))
                for i in range(n):
                    code_i = h_code[i]
                    cond_i, _ = self.WMO_CODES.get(code_i, ("Variabile", "cloud-sun"))
                    item = {
                        "time": h_time[i],
                        "precip_mm": h_prec[i] if h_prec[i] is not None else 0,
                        "prob": (h_prob[i] if i < len(h_prob) else None),
                        "code": code_i,
                        "condition": cond_i,
                    }
                    data["hourly"].append(item)
            except Exception:
                pass

            return {"status": "ok", "message": f"Meteo a {name}: {data['temp']}°C", "data": data}
        except Exception as e:
            return {"status": "error", "message": str(e)}
