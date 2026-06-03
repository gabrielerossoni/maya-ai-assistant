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
