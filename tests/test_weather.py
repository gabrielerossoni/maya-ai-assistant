import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Aggiungi la root del progetto al path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.weather_tool import WeatherTool


def test_weather_tool_text_location():
    tool = WeatherTool()
    with patch("requests.get") as mock_get:
        # Mock geocoding response
        mock_geo = MagicMock()
        mock_geo.json.return_value = {"results": [{"latitude": 45.46, "longitude": 9.19, "name": "Milano"}]}

        # Mock weather response
        mock_weather = MagicMock()
        mock_weather.json.return_value = {
            "current_weather": {"temperature": 22.5, "windspeed": 12.0, "weathercode": 0},
            "hourly": {"relativehumidity_2m": [50], "surface_pressure": [1013], "visibility": [10000]},
            "daily": {
                "time": ["2026-05-20", "2026-05-21", "2026-05-22", "2026-05-23", "2026-05-24", "2026-05-25"],
                "temperature_2m_max": [25.0, 26.0, 27.0, 28.0, 29.0, 30.0],
                "temperature_2m_min": [15.0, 16.0, 17.0, 18.0, 19.0, 20.0],
                "weathercode": [0, 1, 2, 3, 45, 48],
                "precipitation_probability_max": [0, 10, 20, 30, 40, 50],
            },
        }

        mock_get.side_effect = [mock_geo, mock_weather]

        res = tool.execute({"location": "Milano"})
        assert res["status"] == "ok"
        assert res["data"]["location"] == "Milano"
        assert res["data"]["temp"] == 22.5
        assert res["data"]["humidity"] == 50
        assert res["data"]["daily"][0]["precip_probability"] == 10


def test_weather_tool_coordinates_nominatim_success():
    tool = WeatherTool()
    with patch("requests.get") as mock_get:
        # Mock Nominatim response
        mock_nominatim = MagicMock()
        mock_nominatim.json.return_value = {"address": {"city": "Milano"}}

        # Mock weather response
        mock_weather = MagicMock()
        mock_weather.json.return_value = {
            "current_weather": {"temperature": 18.0, "windspeed": 5.0, "weathercode": 1},
            "hourly": {"relativehumidity_2m": [60], "surface_pressure": [1011], "visibility": [8000]},
            "daily": {
                "time": ["2026-05-20", "2026-05-21", "2026-05-22", "2026-05-23", "2026-05-24", "2026-05-25"],
                "temperature_2m_max": [20.0, 21.0, 22.0, 23.0, 24.0, 25.0],
                "temperature_2m_min": [12.0, 13.0, 14.0, 15.0, 16.0, 17.0],
                "weathercode": [1, 2, 3, 45, 48, 51],
            },
        }

        mock_get.side_effect = [mock_nominatim, mock_weather]

        res = tool.execute({"lat": 45.4642, "lon": 9.1899})
        assert res["status"] == "ok"
        assert res["data"]["location"] == "Milano"
        assert res["data"]["temp"] == 18.0
        assert res["data"]["lat"] == 45.4642
        assert res["data"]["lon"] == 9.1899


def test_weather_tool_coordinates_nominatim_failure_fallback():
    tool = WeatherTool()
    with patch("requests.get") as mock_get:
        # Mock weather response
        mock_weather = MagicMock()
        mock_weather.json.return_value = {
            "current_weather": {"temperature": 18.0, "windspeed": 5.0, "weathercode": 1},
            "hourly": {"relativehumidity_2m": [60], "surface_pressure": [1011], "visibility": [8000]},
            "daily": {
                "time": ["2026-05-20", "2026-05-21", "2026-05-22", "2026-05-23", "2026-05-24", "2026-05-25"],
                "temperature_2m_max": [20.0, 21.0, 22.0, 23.0, 24.0, 25.0],
                "temperature_2m_min": [12.0, 13.0, 14.0, 15.0, 16.0, 17.0],
                "weathercode": [1, 2, 3, 45, 48, 51],
            },
        }

        # First call is Nominatim (which throws/fails), second call is weather forecast
        mock_get.side_effect = [Exception("Timeout"), mock_weather]

        res = tool.execute({"lat": 45.46, "lon": 9.19})
        assert res["status"] == "ok"
        # Falls back to "Lat 45.46, Lon 9.19"
        assert "Lat 45.46" in res["data"]["location"]
        assert res["data"]["temp"] == 18.0


def test_weather_tool_falls_back_to_wttr_when_open_meteo_forecast_fails():
    tool = WeatherTool()
    with patch("requests.get") as mock_get:
        mock_geo = MagicMock()
        mock_geo.json.return_value = {"results": [{"latitude": 41.89, "longitude": 12.51, "name": "Roma"}]}

        mock_forecast_error = MagicMock()
        mock_forecast_error.status_code = 502
        mock_forecast_error.url = "https://api.open-meteo.com/v1/forecast"
        mock_forecast_error.text = "<html>Bad Gateway</html>"
        mock_forecast_error.headers = {"content-type": "text/html"}

        mock_wttr = MagicMock()
        mock_wttr.status_code = 200
        mock_wttr.headers = {"content-type": "application/json"}
        mock_wttr.json.return_value = {
            "nearest_area": [
                {
                    "areaName": [{"value": "Roma"}],
                    "region": [{"value": "Lazio"}],
                }
            ],
            "current_condition": [
                {
                    "temp_C": "24",
                    "windspeedKmph": "7",
                    "FeelsLikeC": "25",
                    "humidity": "55",
                    "pressure": "1012",
                    "visibility": "10",
                    "weatherCode": "116",
                    "weatherDesc": [{"value": "Partly cloudy"}],
                }
            ],
            "weather": [
                {
                    "date": "2026-06-04",
                    "maxtempC": "27",
                    "mintempC": "18",
                    "hourly": [
                        {
                            "time": "1200",
                            "weatherCode": "116",
                            "weatherDesc": [{"value": "Partly cloudy"}],
                            "chanceofrain": "10",
                            "precipMM": "0.0",
                        }
                    ],
                },
                {
                    "date": "2026-06-05",
                    "maxtempC": "28",
                    "mintempC": "19",
                    "hourly": [
                        {
                            "time": "1200",
                            "weatherCode": "113",
                            "weatherDesc": [{"value": "Sunny"}],
                            "chanceofrain": "0",
                            "precipMM": "0.0",
                        }
                    ],
                },
            ],
        }

        mock_get.side_effect = [mock_geo, mock_forecast_error, mock_wttr]

        res = tool.execute({"location": "Roma"})
        assert res["status"] == "ok"
        assert res["data"]["provider"] == "wttr.in"
        assert res["data"]["temp"] == 24.0
        assert res["data"]["condition"] == "Parzialm. Nuvoloso"
        assert res["data"]["daily"][0]["max"] == 28.0


def test_weather_tool_returns_structured_error_when_all_providers_fail():
    tool = WeatherTool()
    with patch("requests.get") as mock_get:
        mock_geo_error = MagicMock()
        mock_geo_error.status_code = 500
        mock_geo_error.url = "https://geocoding-api.open-meteo.com/v1/search"
        mock_geo_error.text = "server error"
        mock_geo_error.headers = {"content-type": "text/plain"}

        mock_wttr_error = MagicMock()
        mock_wttr_error.status_code = 502
        mock_wttr_error.url = "https://wttr.in/Roma"
        mock_wttr_error.text = "bad gateway"
        mock_wttr_error.headers = {"content-type": "text/plain"}

        mock_get.side_effect = [mock_geo_error, mock_wttr_error]

        res = tool.execute({"location": "Roma"})

    assert res["status"] == "error"
    assert "Meteo non disponibile" in res["message"]


def test_weather_tool_get_json_rejects_non_json_response():
    tool = WeatherTool()
    with patch("requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.url = "https://example.test/weather"
        mock_response.headers = {"content-type": "text/html"}
        mock_response.text = "<html>not json</html>"
        mock_response.json.side_effect = ValueError("not json")
        mock_get.return_value = mock_response

        with pytest.raises(RuntimeError, match="Risposta non JSON"):
            tool._get_json("https://example.test/weather", timeout=1)
