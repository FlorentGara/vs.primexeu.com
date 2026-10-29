# Project startup

When the user asks to start this project, start the current VS Tools application (`hetzner_url_dashboard.py`) on port 8791. Use Python 3.11 because the application imports `cgi`, which is unavailable in the default Python 3.14 runtime. Set `VS_ROOT` to the VS picture share configured in `run_web_dashboard.ps1`, then verify `http://127.0.0.1:8791/login` responds. Never start the legacy `web_dashboard.py` application on port 8780 for this request.
