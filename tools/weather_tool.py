"""
weather_tool.py - API meteo via Open-Meteo con fallback wttr.in
"""

import os
from urllib.parse import quote

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

    WTTR_DESCRIPTIONS = {
        "clear": ("Sereno", "sun"),
        "sunny": ("Sereno", "sun"),
        "partly cloudy": ("Parzialm. Nuvoloso", "cloud-sun"),
        "cloudy": ("Nuvoloso", "cloud"),
        "overcast": ("Coperto", "cloud"),
        "mist": ("Nebbia", "cloud-fog"),
        "fog": ("Nebbia", "cloud-fog"),
        "rain": ("Pioggia", "cloud-rain"),
        "drizzle": ("Pioggerellina", "cloud-drizzle"),
        "snow": ("Neve", "cloud-snow"),
        "thunder": ("Temporale", "cloud-lightning"),
    }

    def execute(self, action: dict) -> dict:
        if not hasattr(self, "_cache"):
            self._cache = {}
            self.CACHE_EXPIRY = 300

        import time

        cache_key = tuple(sorted((k, v) for k, v in action.items() if v is not None))
        now = time.time()
        if cache_key in self._cache:
            cached_data, cached_time = self._cache[cache_key]
            if now - cached_time < self.CACHE_EXPIRY:
                if cached_data.get("status") == "ok" and "data" in cached_data:
                    self._update_context_weather(cached_data["data"].get("icon"))
                return cached_data

        try:
            result = self._execute_uncached(action)
        except Exception as e:
            return {"status": "error", "message": f"Meteo non disponibile. {e}"}
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
        requested_location = action.get("location") or os.getenv("DEFAULT_WEATHER_LOCATION", "Roma")
        name = None

        if lat is not None and lon is not None:
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
            if not requested_location:
                return {
                    "status": "error",
                    "message": "Localita non specificata. Fornire 'location' o impostare 'DEFAULT_WEATHER_LOCATION'.",
                }

            geo_url = (
                "https://geocoding-api.open-meteo.com/v1/search"
                f"?name={quote(str(requested_location))}&count=1&language=it&format=json"
            )
            try:
                geo_res = self._get_json(geo_url, timeout=3)
                if "results" not in geo_res or len(geo_res["results"]) == 0:
                    return self._execute_wttr(location=requested_location, name=str(requested_location))

                res0 = geo_res["results"][0]
                lat, lon, name = res0["latitude"], res0["longitude"], res0["name"]
            except Exception as e:
                return self._execute_wttr(location=requested_location, name=str(requested_location), primary_error=e)

        try:
            weather_url = (
                f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                "&current=temperature_2m,wind_speed_10m,weather_code,apparent_temperature"
                "&hourly=relative_humidity_2m,surface_pressure,visibility,precipitation,precipitation_probability,weather_code"
                "&daily=temperature_2m_max,temperature_2m_min,weather_code,precipitation_probability_max"
                "&timezone=auto"
            )
            w_res = self._get_json(weather_url, timeout=4)
            return self._parse_open_meteo(w_res, lat=lat, lon=lon, name=name)
        except Exception as e:
            return self._execute_wttr(location=requested_location, lat=lat, lon=lon, name=name, primary_error=e)

    def _parse_open_meteo(self, w_res: dict, lat, lon, name: str | None) -> dict:
        current = w_res.get("current") or w_res.get("current_weather", {})
        daily = w_res.get("daily", {})
        hourly = w_res.get("hourly", {})

        code = current.get("weather_code", current.get("weathercode"))
        condition, icon = self.WMO_CODES.get(code, ("Variabile", "cloud-sun"))

        humidity = self._first(hourly.get("relative_humidity_2m"), hourly.get("relativehumidity_2m"))
        pressure = self._first(hourly.get("surface_pressure"))
        visibility_m = self._first(hourly.get("visibility"))
        visibility_km = round(visibility_m / 1000, 1) if visibility_m else None

        data = {
            "location": name,
            "lat": lat,
            "lon": lon,
            "temp": current.get("temperature_2m", current.get("temperature")),
            "wind": current.get("wind_speed_10m", current.get("windspeed")),
            "feels_like": current.get("apparent_temperature"),
            "humidity": humidity,
            "pressure": round(pressure) if pressure else None,
            "visibility": visibility_km,
            "code": code,
            "condition": condition,
            "icon": icon,
            "daily": [],
            "hourly": [],
            "provider": "open-meteo",
        }

        try:
            t_arr = daily.get("time") or []
            w_arr = daily.get("weather_code") or daily.get("weathercode") or []
            mx = daily.get("temperature_2m_max") or []
            mn = daily.get("temperature_2m_min") or []
            pr = daily.get("precipitation_probability_max") or []
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
                        "precip_probability": pr[i] if i < len(pr) else None,
                    }
                )
        except Exception:
            pass

        try:
            h_time = hourly.get("time") or []
            h_prec = hourly.get("precipitation") or []
            h_prob = hourly.get("precipitation_probability") or []
            h_code = hourly.get("weather_code") or hourly.get("weathercode") or []
            n = min(len(h_time), len(h_prec), len(h_code))
            for i in range(n):
                code_i = h_code[i]
                cond_i, _ = self.WMO_CODES.get(code_i, ("Variabile", "cloud-sun"))
                data["hourly"].append(
                    {
                        "time": h_time[i],
                        "precip_mm": h_prec[i] if h_prec[i] is not None else 0,
                        "prob": h_prob[i] if i < len(h_prob) else None,
                        "code": code_i,
                        "condition": cond_i,
                    }
                )
        except Exception:
            pass

        return {"status": "ok", "message": f"Meteo a {name}: {data['temp']} C", "data": data}

    def _execute_wttr(
        self,
        location: str | None,
        lat=None,
        lon=None,
        name: str | None = None,
        primary_error: Exception | None = None,
    ) -> dict:
        query = location or (f"{lat},{lon}" if lat is not None and lon is not None else None)
        if not query:
            detail = f" Dettaglio Open-Meteo: {primary_error}" if primary_error else ""
            return {"status": "error", "message": f"Meteo non disponibile.{detail}"}

        try:
            url = f"https://wttr.in/{quote(str(query))}?format=j1&m"
            payload = self._get_json(url, timeout=6)
            current = self._first(payload.get("current_condition")) or {}
            nearest_area = self._first(payload.get("nearest_area")) or {}
            area_name = self._first(nearest_area.get("areaName")) or {}
            region = self._first(nearest_area.get("region")) or {}
            resolved_name = name or area_name.get("value") or str(query)
            if region.get("value") and region.get("value") not in resolved_name:
                resolved_name = f"{resolved_name}, {region.get('value')}"

            desc_obj = self._first(current.get("weatherDesc")) or {}
            condition, icon = self._condition_from_wttr(desc_obj.get("value"))

            data = {
                "location": resolved_name,
                "lat": lat,
                "lon": lon,
                "temp": self._to_float(current.get("temp_C")),
                "wind": self._to_float(current.get("windspeedKmph")),
                "feels_like": self._to_float(current.get("FeelsLikeC")),
                "humidity": self._to_int(current.get("humidity")),
                "pressure": self._to_int(current.get("pressure")),
                "visibility": self._to_float(current.get("visibility")),
                "code": self._to_int(current.get("weatherCode")),
                "condition": condition,
                "icon": icon,
                "daily": [],
                "hourly": [],
                "provider": "wttr.in",
            }

            for day in (payload.get("weather") or [])[1:6]:
                hourly = day.get("hourly") or []
                mid = hourly[len(hourly) // 2] if hourly else {}
                day_desc = self._first(mid.get("weatherDesc")) or {}
                day_condition, day_icon = self._condition_from_wttr(day_desc.get("value"))
                data["daily"].append(
                    {
                        "date": day.get("date"),
                        "max": self._to_float(day.get("maxtempC")),
                        "min": self._to_float(day.get("mintempC")),
                        "code": self._to_int(mid.get("weatherCode")),
                        "condition": day_condition,
                        "icon": day_icon,
                        "precip_probability": self._to_int(mid.get("chanceofrain")),
                    }
                )

            for day in (payload.get("weather") or [])[:2]:
                date = day.get("date")
                for hour in day.get("hourly") or []:
                    desc_obj = self._first(hour.get("weatherDesc")) or {}
                    hour_condition, _ = self._condition_from_wttr(desc_obj.get("value"))
                    time_value = str(hour.get("time", "0")).zfill(4)
                    data["hourly"].append(
                        {
                            "time": f"{date}T{time_value[:2]}:{time_value[2:]}",
                            "precip_mm": self._to_float(hour.get("precipMM")) or 0,
                            "prob": self._to_int(hour.get("chanceofrain")),
                            "code": self._to_int(hour.get("weatherCode")),
                            "condition": hour_condition,
                        }
                    )

            return {"status": "ok", "message": f"Meteo a {resolved_name}: {data['temp']} C", "data": data}
        except Exception as wttr_error:
            detail = f"Open-Meteo: {primary_error}; wttr.in: {wttr_error}"
            return {"status": "error", "message": f"Meteo non disponibile. {detail}"}

    def _get_json(self, url: str, timeout: int) -> dict:
        headers = {"User-Agent": "MAYA-AI-Assistant/1.0"}
        response = requests.get(url, headers=headers, timeout=timeout)
        status_code = getattr(response, "status_code", 200)
        if not isinstance(status_code, int):
            status_code = 200
        if status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code} da {response.url}")
        try:
            return response.json()
        except ValueError:
            content_type = response.headers.get("content-type", "")
            if not isinstance(content_type, str):
                content_type = ""
            if "json" not in content_type.lower():
                snippet = response.text[:120].replace("\n", " ").replace("\r", " ")
                raise RuntimeError(f"Risposta non JSON da {response.url}: {snippet}")
            raise

    @staticmethod
    def _first(*values):
        for value in values:
            if isinstance(value, list) and value:
                return value[0]
            if value is not None and not isinstance(value, list):
                return value
        return None

    @staticmethod
    def _to_float(value):
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_int(value):
        numeric = WeatherTool._to_float(value)
        return int(round(numeric)) if numeric is not None else None

    def _condition_from_wttr(self, description: str | None) -> tuple[str, str]:
        desc = (description or "Variabile").strip()
        lower = desc.lower()
        for needle, mapped in self.WTTR_DESCRIPTIONS.items():
            if needle in lower:
                return mapped
        return desc, "cloud-sun"
