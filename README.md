# Jharkhand Pollution Intelligence

A Flask web application with a responsive dashboard, district explorer, interactive map, air-quality history/forecast charts, CSV export, community complaint tracking, and a password-protected admin desk.

## Data integrity
- Live values are fetched from the Open-Meteo Air Quality API (CAMS model-based estimates).
- These are **not** CPCB station readings and the US AQI scale is not the Indian CPCB AQI scale.
- If the provider is unavailable, the app reports an error instead of substituting demo numbers.
- District coordinates are approximate locations, not verified monitoring-station coordinates.
- Water-quality measurements are not invented; the complaint form supports water-pollution reports.

## Run on Windows
1. Install Python 3.10+ from https://www.python.org/downloads/ and enable "Add Python to PATH".
2. Open Command Prompt in this folder.
3. Create a virtual environment:
   ```bat
   python -m venv .venv
   .venv\Scripts\activate
   ```
4. Install dependencies:
   ```bat
   python -m pip install -r requirements.txt
   ```
5. Configure a strong admin password and Flask secret for local use:
   ```bat
   set ADMIN_PASSWORD=replace-with-a-long-unique-password
   set FLASK_SECRET_KEY=replace-with-a-long-random-secret
   ```
6. Start:
   ```bat
   python app.py
   ```
7. Open http://127.0.0.1:5000

The database file `pollution.db` is created automatically on first run.

## Linux / macOS
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export ADMIN_PASSWORD='replace-with-a-long-unique-password'
export FLASK_SECRET_KEY='replace-with-a-long-random-secret'
python app.py
```

## Deployment notes
- Do not use Flask's development server for public production hosting. Use Gunicorn or another production WSGI server.
- Set `ADMIN_PASSWORD` and a long random `FLASK_SECRET_KEY` in the hosting provider's environment settings.
- Use HTTPS, backups, a privacy notice, and appropriate access controls before accepting real users' personal/contact information.
- SQLite is suitable for a small local project; consider managed PostgreSQL for multi-user public deployment.
- Open-Meteo and OpenStreetMap/Leaflet are external services, so the dashboard needs internet access.
- For official station readings, obtain and integrate a reliable authorized CPCB/India data source and label station data separately. Do not present model estimates as official measurements.
