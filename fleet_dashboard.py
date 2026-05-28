"""
fleet_dashboard.py
Reads fleet_status.csv and generates a self-contained fleet_dashboard.html.
Python standard library only — no third-party packages.
"""

import csv
import json
import math
import os
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CSV_PATH = os.path.join(os.path.dirname(__file__), "fleet_status.csv")
OUT_PATH = os.path.join(os.path.dirname(__file__), "fleet_dashboard.html")

STATUS_CONFIG = {
    "active":      {"color": "#22c55e", "label": "Active",      "order": 0},
    "idle":        {"color": "#f59e0b", "label": "Idle",        "order": 1},
    "low_battery": {"color": "#ef4444", "label": "Low Battery", "order": 2},
    "offline":     {"color": "#6b7280", "label": "Offline",     "order": 3},
    "unknown":     {"color": "#a855f7", "label": "Unknown",     "order": 4},
}

KNOWN_STATUSES = {"active", "idle", "offline", "low_battery"}

# ---------------------------------------------------------------------------
# Data loading & validation
# ---------------------------------------------------------------------------

def parse_float(val):
    """Return float or None if invalid."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def parse_battery(val):
    """Clamp battery to 0-100, return None if unparseable."""
    v = parse_float(val)
    if v is None:
        return None
    return max(0, min(100, round(v)))


def parse_datetime(val):
    """Return datetime (naive, treat as local/fleet time) or None."""
    if not val:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(val.strip(), fmt)
        except ValueError:
            continue
    return None


def time_ago(dt, now):
    """Return human-readable 'X ago' string, or 'Unknown' if dt is None or future."""
    if dt is None:
        return "Unknown"
    delta = now - dt
    seconds = delta.total_seconds()
    if seconds < 0:
        return "Future timestamp"
    if seconds < 60:
        return f"{int(seconds)}s ago"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)}d ago"


def load_devices(path):
    devices = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            device_id = (row.get("device_id") or "").strip()
            if not device_id:
                continue

            raw_status = (row.get("status") or "").strip().lower()
            status = raw_status if raw_status in KNOWN_STATUSES else "unknown"

            lat = parse_float(row.get("lat"))
            lon = parse_float(row.get("lon"))
            has_coords = (lat is not None and lon is not None
                          and -90 <= lat <= 90 and -180 <= lon <= 180)

            battery = parse_battery(row.get("battery_pct"))
            dt = parse_datetime(row.get("last_seen"))

            devices.append({
                "id":         device_id,
                "name":       (row.get("name") or "").strip() or device_id,
                "status":     status,
                "raw_status": raw_status,
                "battery":    battery,
                "lat":        lat if has_coords else None,
                "lon":        lon if has_coords else None,
                "has_coords": has_coords,
                "last_seen":  dt.strftime("%Y-%m-%d %H:%M") if dt else "N/A",
                "dt":         dt,
                "location":   (row.get("location") or "").strip() or "Unknown",
            })
    return devices


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def build_summary(devices):
    counts = {k: 0 for k in STATUS_CONFIG}
    for d in devices:
        counts[d["status"]] += 1
    return counts


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

def device_to_json_dict(d, now):
    """Serialise a device for the embedded JS payload."""
    return {
        "id": d["id"],
        "name": d["name"],
        "status": d["status"],
        "raw_status": d["raw_status"],
        "battery": d["battery"],
        "lat": d["lat"],
        "lon": d["lon"],
        "has_coords": d["has_coords"],
        "last_seen": d["last_seen"],
        "last_seen_epoch": int(d["dt"].timestamp()) if d["dt"] else None,
        "location": d["location"],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

MAPLIBRE_CSS = "https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css"
MAPLIBRE_JS  = "https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"

# NOTE: The requirement says "no external files" for the HTML output.
# MapLibre GL JS is loaded from CDN for the 3D map; the dashboard HTML
# itself is a single file. Inlining ~600 KB of map library would require
# third-party tooling and isn't practical.

def generate_html(devices, now):
    summary = build_summary(devices)
    total = len(devices)
    generated_at = now.strftime("%Y-%m-%d %H:%M:%S")
    now_epoch = int(now.timestamp())

    # Aggregate stats
    batteries = [d["battery"] for d in devices if d["battery"] is not None]
    avg_battery = round(sum(batteries) / len(batteries)) if batteries else 0
    online_count = summary.get("active", 0) + summary.get("idle", 0)
    issues_count = summary.get("low_battery", 0) + summary.get("offline", 0) + summary.get("unknown", 0)
    no_gps_count = sum(1 for d in devices if not d["has_coords"])

    # Activity feed (most recent events first)
    sorted_by_time = sorted(
        [d for d in devices if d["dt"] is not None],
        key=lambda d: d["dt"], reverse=True
    )[:8]
    activity = []
    for d in sorted_by_time:
        cfg = STATUS_CONFIG.get(d["status"], STATUS_CONFIG["unknown"])
        activity.append({
            "id": d["id"], "name": d["name"], "status": d["status"],
            "label": cfg["label"], "color": cfg["color"],
            "location": d["location"], "epoch": int(d["dt"].timestamp()),
        })

    # Compute map centre + bounds
    valid = [d for d in devices if d["has_coords"]]
    if valid:
        center_lat = sum(d["lat"] for d in valid) / len(valid)
        center_lon = sum(d["lon"] for d in valid) / len(valid)
    else:
        center_lat, center_lon = -25.2744, 133.7751

    devices_json = json.dumps([device_to_json_dict(d, now) for d in devices])
    activity_json = json.dumps(activity)
    status_config_json = json.dumps(STATUS_CONFIG)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SolidGPS · Fleet Command Center</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{MAPLIBRE_CSS}">
<style>
  :root {{
    --bg-0: #0a0e1a;
    --bg-1: #0f1623;
    --bg-2: #161f33;
    --bg-3: #1e2942;
    --border: #243047;
    --text-0: #f1f5f9;
    --text-1: #cbd5e1;
    --text-2: #94a3b8;
    --text-3: #64748b;
    --accent: #38bdf8;
    --accent-glow: rgba(56,189,248,.18);
    --green: #22c55e;
    --amber: #f59e0b;
    --red:   #ef4444;
    --gray:  #6b7280;
    --purple:#a855f7;
  }}
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{ height: 100%; }}
  body {{
    font-family: 'Inter', system-ui, sans-serif;
    background: radial-gradient(1200px 600px at 10% -10%, rgba(56,189,248,.08), transparent 60%),
                radial-gradient(900px 500px at 110% 110%, rgba(168,85,247,.07), transparent 60%),
                var(--bg-0);
    color: var(--text-1);
    overflow: hidden;
    font-feature-settings: "cv11", "ss01";
  }}
  ::-webkit-scrollbar {{ width: 8px; height: 8px; }}
  ::-webkit-scrollbar-track {{ background: transparent; }}
  ::-webkit-scrollbar-thumb {{ background: #2a3654; border-radius: 4px; }}
  ::-webkit-scrollbar-thumb:hover {{ background: #3a496e; }}

  /* ===== Layout ===== */
  .app {{
    display: grid;
    grid-template-columns: 240px 1fr;
    grid-template-rows: 60px 1fr;
    height: 100vh;
  }}
  .sidebar {{ grid-row: 1 / 3; background: var(--bg-1); border-right: 1px solid var(--border); display: flex; flex-direction: column; }}
  .topbar  {{ background: var(--bg-1); border-bottom: 1px solid var(--border); display: flex; align-items: center; padding: 0 24px; gap: 16px; }}
  .content {{ overflow: auto; padding: 20px 24px; background: var(--bg-0); }}

  /* ===== Sidebar ===== */
  .brand {{ display: flex; align-items: center; gap: 10px; padding: 18px 20px; border-bottom: 1px solid var(--border); }}
  .brand-logo {{
    width: 36px; height: 36px; border-radius: 10px;
    background: linear-gradient(135deg, #22c55e 0%, #38bdf8 100%);
    display: flex; align-items: center; justify-content: center;
    color: #0a0e1a; font-weight: 800; font-size: 18px;
    box-shadow: 0 4px 14px rgba(34,197,94,.3);
  }}
  .brand-text {{ display: flex; flex-direction: column; line-height: 1.1; }}
  .brand-name {{ font-weight: 700; color: var(--text-0); font-size: 14px; letter-spacing: .02em; }}
  .brand-sub  {{ font-size: 10.5px; color: var(--text-3); text-transform: uppercase; letter-spacing: .12em; margin-top: 3px; }}
  .nav {{ padding: 14px 12px; flex: 1; }}
  .nav-section {{ font-size: 10.5px; color: var(--text-3); text-transform: uppercase; letter-spacing: .14em; padding: 12px 10px 6px; }}
  .nav-item {{
    display: flex; align-items: center; gap: 12px;
    padding: 10px 12px; border-radius: 8px; cursor: pointer;
    color: var(--text-2); font-size: 13.5px; font-weight: 500;
    transition: all .15s;
  }}
  .nav-item:hover {{ background: var(--bg-2); color: var(--text-0); }}
  .nav-item.active {{ background: linear-gradient(90deg, var(--accent-glow), transparent); color: var(--text-0); position: relative; }}
  .nav-item.active::before {{ content: ''; position: absolute; left: 0; top: 8px; bottom: 8px; width: 3px; background: var(--accent); border-radius: 0 3px 3px 0; }}
  .nav-item svg {{ width: 18px; height: 18px; flex-shrink: 0; opacity: .8; }}
  .nav-item .nav-badge {{ margin-left: auto; background: var(--red); color: #fff; font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 999px; }}
  .sidebar-footer {{ padding: 14px 16px; border-top: 1px solid var(--border); display: flex; align-items: center; gap: 10px; }}
  .avatar {{ width: 32px; height: 32px; border-radius: 50%; background: linear-gradient(135deg,#a855f7,#38bdf8); display: flex; align-items: center; justify-content: center; color: #fff; font-weight: 700; font-size: 13px; }}
  .user-meta {{ display: flex; flex-direction: column; line-height: 1.2; }}
  .user-name {{ font-size: 13px; color: var(--text-0); font-weight: 600; }}
  .user-role {{ font-size: 11px; color: var(--text-3); }}

  /* ===== Topbar ===== */
  .breadcrumb {{ font-size: 13px; color: var(--text-2); }}
  .breadcrumb b {{ color: var(--text-0); font-weight: 600; }}
  .topbar-search {{ flex: 1; max-width: 420px; position: relative; }}
  .topbar-search input {{
    width: 100%; padding: 9px 14px 9px 38px; border-radius: 8px;
    background: var(--bg-2); border: 1px solid var(--border); color: var(--text-0);
    font-size: 13px; font-family: inherit; outline: none; transition: border-color .15s, box-shadow .15s;
  }}
  .topbar-search input::placeholder {{ color: var(--text-3); }}
  .topbar-search input:focus {{ border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-glow); }}
  .topbar-search svg {{ position: absolute; left: 12px; top: 50%; transform: translateY(-50%); width: 16px; height: 16px; color: var(--text-3); }}
  .topbar-actions {{ display: flex; align-items: center; gap: 12px; margin-left: auto; }}
  .live-pill {{
    display: inline-flex; align-items: center; gap: 8px;
    padding: 6px 12px; border-radius: 999px;
    background: rgba(34,197,94,.1); border: 1px solid rgba(34,197,94,.3);
    font-size: 11.5px; font-weight: 600; color: #4ade80; letter-spacing: .04em;
  }}
  .pulse-dot {{ width: 8px; height: 8px; border-radius: 50%; background: #22c55e; box-shadow: 0 0 0 0 rgba(34,197,94,.7); animation: pulse 2s infinite; }}
  @keyframes pulse {{ 0% {{ box-shadow: 0 0 0 0 rgba(34,197,94,.7); }} 70% {{ box-shadow: 0 0 0 10px rgba(34,197,94,0); }} 100% {{ box-shadow: 0 0 0 0 rgba(34,197,94,0); }} }}
  .topbar-clock {{ font-family: 'JetBrains Mono', monospace; font-size: 13px; color: var(--text-1); padding: 6px 10px; background: var(--bg-2); border: 1px solid var(--border); border-radius: 8px; }}
  .icon-btn {{ width: 36px; height: 36px; border-radius: 8px; background: var(--bg-2); border: 1px solid var(--border); display: flex; align-items: center; justify-content: center; cursor: pointer; color: var(--text-2); transition: all .15s; position: relative; }}
  .icon-btn:hover {{ background: var(--bg-3); color: var(--text-0); }}
  .icon-btn svg {{ width: 16px; height: 16px; }}
  .icon-btn .dot {{ position: absolute; top: 7px; right: 7px; width: 8px; height: 8px; background: var(--red); border-radius: 50%; border: 2px solid var(--bg-1); }}

  /* ===== KPI Cards ===== */
  .kpi-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 18px; }}
  .kpi {{
    background: linear-gradient(180deg, var(--bg-2) 0%, var(--bg-1) 100%);
    border: 1px solid var(--border); border-radius: 14px; padding: 16px 18px;
    position: relative; overflow: hidden; transition: transform .2s, border-color .2s;
  }}
  .kpi:hover {{ transform: translateY(-2px); border-color: #2f3d5c; }}
  .kpi-top {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }}
  .kpi-label {{ font-size: 11px; font-weight: 600; color: var(--text-3); text-transform: uppercase; letter-spacing: .1em; }}
  .kpi-icon {{ width: 36px; height: 36px; border-radius: 10px; display: flex; align-items: center; justify-content: center; }}
  .kpi-icon svg {{ width: 18px; height: 18px; }}
  .kpi-value {{ font-size: 30px; font-weight: 800; color: var(--text-0); line-height: 1; letter-spacing: -.02em; }}
  .kpi-meta {{ font-size: 12px; color: var(--text-2); margin-top: 8px; display: flex; align-items: center; gap: 6px; }}
  .kpi-meta .delta-up {{ color: #4ade80; font-weight: 600; }}
  .kpi-meta .delta-down {{ color: #f87171; font-weight: 600; }}
  .kpi-bar {{ height: 4px; background: var(--bg-3); border-radius: 2px; margin-top: 10px; overflow: hidden; }}
  .kpi-bar-fill {{ height: 100%; border-radius: 2px; transition: width .6s; }}

  /* ===== Main grid ===== */
  .main-grid {{ display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 16px; height: calc(100vh - 60px - 40px - 18px - 130px); min-height: 480px; }}
  @media (max-width: 1100px) {{ .main-grid {{ grid-template-columns: 1fr; height: auto; }} .map-panel {{ height: 480px; }} }}

  .panel {{ background: var(--bg-1); border: 1px solid var(--border); border-radius: 14px; overflow: hidden; display: flex; flex-direction: column; }}
  .panel-head {{ padding: 14px 18px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border); }}
  .panel-title {{ font-size: 13px; font-weight: 600; color: var(--text-0); display: flex; align-items: center; gap: 8px; }}
  .panel-title .count-pill {{ background: var(--bg-3); color: var(--text-2); font-size: 11px; padding: 2px 8px; border-radius: 999px; font-weight: 500; }}

  /* ===== Sidebar mini-stats ===== */
  .nav-mini-stats {{ margin-top: 18px; padding: 14px 12px; background: var(--bg-2); border: 1px solid var(--border); border-radius: 10px; display: flex; flex-direction: column; gap: 10px; }}
  .mini-stat {{ display: flex; justify-content: space-between; align-items: center; }}
  .mini-stat-label {{ font-size: 11px; color: var(--text-3); text-transform: uppercase; letter-spacing: .08em; font-weight: 600; }}
  .mini-stat-value {{ font-size: 18px; font-weight: 700; color: var(--text-0); font-family: 'JetBrains Mono', monospace; }}

  /* ===== Map ===== */
  .map-panel {{ position: relative; }}
  #map {{ flex: 1; background: var(--bg-2); position: relative; }}
  .map-toolbar {{ display: flex; gap: 6px; flex-wrap: wrap; padding: 10px 16px; border-bottom: 1px solid var(--border); align-items: center; background: var(--bg-1); }}

  /* MapLibre custom styling */
  .maplibregl-map {{ font-family: 'Inter', sans-serif; }}
  .maplibregl-popup-content {{ background: var(--bg-2) !important; color: var(--text-0) !important; border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; font-size: 12.5px; line-height: 1.55; box-shadow: 0 12px 40px rgba(0,0,0,.5); }}
  .maplibregl-popup-tip {{ border-top-color: var(--bg-2) !important; border-bottom-color: var(--bg-2) !important; }}
  .maplibregl-popup-close-button {{ color: var(--text-2) !important; font-size: 16px !important; padding: 4px 8px !important; }}
  .maplibregl-popup-close-button:hover {{ background: transparent !important; color: var(--text-0) !important; }}
  .maplibregl-ctrl-attrib {{ background: rgba(15,22,35,.85) !important; color: var(--text-3) !important; }}
  .maplibregl-ctrl-attrib a {{ color: var(--text-2) !important; }}
  .maplibregl-ctrl button {{ background: var(--bg-2) !important; border: 1px solid var(--border) !important; }}
  .maplibregl-ctrl button:hover {{ background: var(--bg-3) !important; }}
  .maplibregl-ctrl button .maplibregl-ctrl-icon {{ filter: invert(0.85); }}
  .maplibregl-ctrl-group {{ background: transparent !important; border-radius: 8px !important; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,.4) !important; }}

  /* Map overlays */
  .map-overlay {{ position: absolute; z-index: 5; }}
  .chip {{
    display: inline-flex; align-items: center; gap: 7px;
    padding: 7px 12px; border-radius: 999px; font-size: 12px; font-weight: 600;
    background: rgba(15,22,35,.9); backdrop-filter: blur(8px);
    border: 1px solid var(--border); color: var(--text-1);
    cursor: pointer; transition: all .15s; user-select: none;
  }}
  .chip:hover {{ border-color: #3a496e; color: var(--text-0); }}
  .chip.active {{ background: var(--bg-3); border-color: var(--accent); color: var(--text-0); }}
  .chip-dot {{ width: 8px; height: 8px; border-radius: 50%; }}
  .chip .count {{ font-size: 11px; color: var(--text-3); font-weight: 500; margin-left: 2px; }}
  .chip.active .count {{ color: var(--text-1); }}

  .map-head-actions {{ display: flex; gap: 8px; align-items: center; }}
  .pitch-indicator {{ font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--accent); padding: 4px 8px; background: rgba(56,189,248,.1); border: 1px solid rgba(56,189,248,.3); border-radius: 6px; font-weight: 600; }}
  .map-action-btn {{ display: inline-flex; align-items: center; gap: 5px; padding: 5px 10px; background: var(--bg-2); border: 1px solid var(--border); border-radius: 6px; color: var(--text-1); font-size: 11.5px; font-weight: 600; cursor: pointer; font-family: inherit; transition: all .15s; }}
  .map-action-btn:hover {{ background: var(--bg-3); color: var(--text-0); }}
  .map-action-btn.active {{ background: rgba(56,189,248,.15); border-color: var(--accent); color: var(--accent); }}

  .map-legend-card {{
    bottom: 14px; left: 14px;
    background: rgba(15,22,35,.92); backdrop-filter: blur(8px);
    border: 1px solid var(--border); border-radius: 10px;
    padding: 10px 12px; font-size: 11.5px; min-width: 160px;
  }}
  .map-legend-card-title {{ font-size: 10px; font-weight: 700; color: var(--text-3); text-transform: uppercase; letter-spacing: .12em; margin-bottom: 8px; }}
  .legend-item {{ display: flex; align-items: center; gap: 8px; padding: 3px 0; color: var(--text-1); }}
  .legend-dot {{ width: 10px; height: 10px; border-radius: 50%; }}

  /* Custom markers */
  .pin {{ width: 18px; height: 18px; border-radius: 50%; border: 2px solid #fff; box-shadow: 0 2px 6px rgba(0,0,0,.5); position: relative; }}
  .pin.critical::after {{
    content: ''; position: absolute; inset: -6px; border-radius: 50%;
    border: 2px solid currentColor; opacity: .8; animation: ping 1.6s cubic-bezier(0,0,.2,1) infinite;
  }}
  @keyframes ping {{ 0% {{ transform: scale(.6); opacity: .8; }} 100% {{ transform: scale(2.2); opacity: 0; }} }}

  /* ===== Right panel (devices) ===== */
  .device-panel {{ display: flex; flex-direction: column; min-height: 0; }}
  .panel-tabs {{ display: flex; border-bottom: 1px solid var(--border); padding: 0 18px; }}
  .panel-tab {{ padding: 12px 14px; font-size: 12.5px; font-weight: 600; color: var(--text-3); cursor: pointer; border-bottom: 2px solid transparent; transition: all .15s; }}
  .panel-tab:hover {{ color: var(--text-1); }}
  .panel-tab.active {{ color: var(--text-0); border-bottom-color: var(--accent); }}
  .device-search {{ padding: 12px 16px; border-bottom: 1px solid var(--border); position: relative; }}
  .device-search input {{ width: 100%; padding: 8px 12px 8px 34px; border-radius: 8px; background: var(--bg-2); border: 1px solid var(--border); color: var(--text-0); font-size: 12.5px; outline: none; font-family: inherit; }}
  .device-search input:focus {{ border-color: var(--accent); }}
  .device-search svg {{ position: absolute; left: 26px; top: 50%; transform: translateY(-50%); width: 14px; height: 14px; color: var(--text-3); }}
  .device-list {{ flex: 1; overflow-y: auto; }}
  .device-card {{
    display: grid; grid-template-columns: auto 1fr auto; gap: 10px;
    padding: 12px 16px; border-bottom: 1px solid var(--bg-2);
    cursor: pointer; transition: background .15s;
    align-items: center;
  }}
  .device-card:hover {{ background: var(--bg-2); }}
  .device-card.selected {{ background: var(--bg-2); box-shadow: inset 3px 0 0 var(--accent); }}
  .device-icon {{ width: 36px; height: 36px; border-radius: 10px; background: var(--bg-3); display: flex; align-items: center; justify-content: center; position: relative; }}
  .device-icon svg {{ width: 18px; height: 18px; color: var(--text-1); }}
  .device-icon-dot {{ position: absolute; top: -2px; right: -2px; width: 10px; height: 10px; border-radius: 50%; border: 2px solid var(--bg-1); }}
  .device-main {{ min-width: 0; }}
  .device-name {{ font-size: 13px; font-weight: 600; color: var(--text-0); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .device-sub {{ font-size: 11.5px; color: var(--text-3); margin-top: 2px; display: flex; align-items: center; gap: 6px; }}
  .device-sub .dot-sep {{ width: 3px; height: 3px; background: var(--text-3); border-radius: 50%; display: inline-block; }}
  .device-meta {{ text-align: right; min-width: 70px; }}
  .device-batt {{ font-family: 'JetBrains Mono', monospace; font-size: 12px; font-weight: 600; }}
  .device-time {{ font-size: 10.5px; color: var(--text-3); margin-top: 3px; }}
  .device-empty {{ padding: 30px; text-align: center; color: var(--text-3); font-size: 13px; }}

  /* ===== Bottom row ===== */
  .bottom-row {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; margin-top: 16px; }}
  @media (max-width: 1100px) {{ .bottom-row {{ grid-template-columns: 1fr; }} }}

  /* Activity feed */
  .activity-list {{ max-height: 280px; overflow-y: auto; padding: 6px 0; }}
  .activity-item {{ display: flex; gap: 12px; padding: 10px 18px; border-bottom: 1px solid var(--bg-2); align-items: center; }}
  .activity-item:last-child {{ border-bottom: none; }}
  .activity-bullet {{ width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; box-shadow: 0 0 0 3px rgba(255,255,255,.05); }}
  .activity-text {{ flex: 1; min-width: 0; font-size: 12.5px; color: var(--text-1); }}
  .activity-text b {{ color: var(--text-0); font-weight: 600; }}
  .activity-time {{ font-size: 11px; color: var(--text-3); white-space: nowrap; font-family: 'JetBrains Mono', monospace; }}

  /* Status distribution */
  .status-dist {{ padding: 16px 18px; }}
  .dist-row {{ display: grid; grid-template-columns: 100px 1fr 50px; gap: 10px; align-items: center; padding: 7px 0; font-size: 12.5px; }}
  .dist-label {{ color: var(--text-1); display: flex; align-items: center; gap: 8px; }}
  .dist-bar {{ height: 8px; background: var(--bg-3); border-radius: 4px; overflow: hidden; }}
  .dist-fill {{ height: 100%; border-radius: 4px; transition: width .6s; }}
  .dist-count {{ font-family: 'JetBrains Mono', monospace; text-align: right; color: var(--text-0); font-weight: 600; }}

  /* Battery distribution */
  .batt-dist {{ padding: 16px 18px; }}
  .batt-bins {{ display: flex; gap: 6px; align-items: flex-end; height: 120px; padding: 8px 0; }}
  .batt-bin {{ flex: 1; background: linear-gradient(180deg, var(--accent), #1e6e9b); border-radius: 4px 4px 0 0; min-height: 4px; position: relative; transition: opacity .15s; }}
  .batt-bin:hover {{ opacity: .8; }}
  .batt-bin .bin-tip {{ position: absolute; bottom: 100%; left: 50%; transform: translateX(-50%); background: var(--bg-3); color: var(--text-0); padding: 2px 6px; border-radius: 4px; font-size: 10px; margin-bottom: 4px; opacity: 0; transition: opacity .15s; pointer-events: none; white-space: nowrap; }}
  .batt-bin:hover .bin-tip {{ opacity: 1; }}
  .batt-bin-labels {{ display: flex; gap: 6px; margin-top: 4px; }}
  .batt-bin-label {{ flex: 1; text-align: center; font-size: 10px; color: var(--text-3); font-family: 'JetBrains Mono', monospace; }}

  /* Status badges */
  .status-badge {{ display: inline-flex; align-items: center; gap: 5px; padding: 3px 9px; border-radius: 999px; font-size: 10.5px; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; }}
  .status-badge .bd {{ width: 6px; height: 6px; border-radius: 50%; }}

  /* Footer note */
  .footnote {{ text-align: center; padding: 14px 0 4px; font-size: 11px; color: var(--text-3); }}
  .footnote code {{ background: var(--bg-2); padding: 2px 6px; border-radius: 4px; color: var(--text-2); }}
</style>
</head>
<body>
<div class="app">
  <!-- ============ SIDEBAR ============ -->
  <aside class="sidebar">
    <div class="brand">
      <div class="brand-logo">S</div>
      <div class="brand-text">
        <div class="brand-name">SolidGPS</div>
        <div class="brand-sub">Fleet Command</div>
      </div>
    </div>
    <nav class="nav">
      <div class="nav-section">Operations</div>
      <div class="nav-item active">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
        Dashboard
      </div>
      <div class="nav-mini-stats">
        <div class="mini-stat">
          <div class="mini-stat-label">Fleet Size</div>
          <div class="mini-stat-value">{total}</div>
        </div>
        <div class="mini-stat">
          <div class="mini-stat-label">Active</div>
          <div class="mini-stat-value" style="color:var(--green)">{summary.get('active',0)}</div>
        </div>
        <div class="mini-stat">
          <div class="mini-stat-label">Issues</div>
          <div class="mini-stat-value" style="color:var(--red)">{issues_count}</div>
        </div>
      </div>
    </nav>
    <div class="sidebar-footer">
      <div class="avatar">FM</div>
      <div class="user-meta">
        <div class="user-name">Fleet Manager</div>
        <div class="user-role">Operations · AEST</div>
      </div>
    </div>
  </aside>

  <!-- ============ TOPBAR ============ -->
  <header class="topbar">
    <div class="breadcrumb">Operations &nbsp;/&nbsp; <b>Live Dashboard</b></div>
    <div class="topbar-search">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.35-4.35"/></svg>
      <input id="globalSearch" placeholder="Search devices, locations, IDs…" autocomplete="off">
    </div>
    <div class="topbar-actions">
      <div class="live-pill"><span class="pulse-dot"></span>LIVE</div>
      <div class="topbar-clock" id="clock">--:--:--</div>
      <div class="icon-btn" title="Reset map view" id="resetView">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
      </div>
      <div class="icon-btn" title="Refresh data" onclick="location.reload()">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0114.85-3.36L23 10"/><path d="M20.49 15a9 9 0 01-14.85 3.36L1 14"/></svg>
      </div>
    </div>
  </header>

  <!-- ============ CONTENT ============ -->
  <main class="content">
    <!-- KPI cards -->
    <div class="kpi-grid">
      <div class="kpi">
        <div class="kpi-top">
          <div class="kpi-label">Total Fleet</div>
          <div class="kpi-icon" style="background:rgba(56,189,248,.15);color:var(--accent)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 17h2l1-6h12l1 6h2"/><circle cx="7" cy="17" r="2"/><circle cx="17" cy="17" r="2"/></svg>
          </div>
        </div>
        <div class="kpi-value">{total}</div>
        <div class="kpi-meta"><span class="delta-up">▲ {online_count}</span> online · {no_gps_count} no GPS</div>
        <div class="kpi-bar"><div class="kpi-bar-fill" style="width:{(online_count/total*100) if total else 0:.0f}%;background:var(--accent)"></div></div>
      </div>
      <div class="kpi">
        <div class="kpi-top">
          <div class="kpi-label">Active Now</div>
          <div class="kpi-icon" style="background:rgba(34,197,94,.15);color:var(--green)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
          </div>
        </div>
        <div class="kpi-value">{summary.get("active",0)}</div>
        <div class="kpi-meta"><span class="delta-up">▲</span> Moving / reporting</div>
        <div class="kpi-bar"><div class="kpi-bar-fill" style="width:{(summary.get('active',0)/total*100) if total else 0:.0f}%;background:var(--green)"></div></div>
      </div>
      <div class="kpi">
        <div class="kpi-top">
          <div class="kpi-label">Critical Issues</div>
          <div class="kpi-icon" style="background:rgba(239,68,68,.15);color:var(--red)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>
          </div>
        </div>
        <div class="kpi-value">{issues_count}</div>
        <div class="kpi-meta"><span class="delta-down">▼</span> Low battery + offline</div>
        <div class="kpi-bar"><div class="kpi-bar-fill" style="width:{(issues_count/total*100) if total else 0:.0f}%;background:var(--red)"></div></div>
      </div>
      <div class="kpi">
        <div class="kpi-top">
          <div class="kpi-label">Avg Battery</div>
          <div class="kpi-icon" style="background:rgba(245,158,11,.15);color:var(--amber)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="7" width="18" height="10" rx="2"/><line x1="22" y1="11" x2="22" y2="13"/></svg>
          </div>
        </div>
        <div class="kpi-value">{avg_battery}<span style="font-size:18px;color:var(--text-2);font-weight:600">%</span></div>
        <div class="kpi-meta">Across {len(batteries)} reporting units</div>
        <div class="kpi-bar"><div class="kpi-bar-fill" style="width:{avg_battery}%;background:var(--amber)"></div></div>
      </div>
    </div>

    <!-- Map + Device panel -->
    <div class="main-grid">
      <div class="panel map-panel">
        <div class="panel-head">
          <div class="panel-title">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z"/><circle cx="12" cy="10" r="3"/></svg>
            3D Live Map
            <span class="count-pill" id="mapCount">{len(valid)} plotted</span>
          </div>
          <div class="map-head-actions">
            <span class="pitch-indicator" id="pitchInd" title="Map pitch">3D · 45°</span>
            <button class="map-action-btn" id="toggle3D" title="Toggle 2D/3D view">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
              <span>3D</span>
            </button>
          </div>
        </div>

        <!-- Filter chips toolbar (no longer overlapping) -->
        <div class="map-toolbar" id="filterChips">
          <div class="chip active" data-filter="all">All <span class="count">{total}</span></div>
          <div class="chip" data-filter="active"><span class="chip-dot" style="background:var(--green)"></span>Active <span class="count">{summary.get("active",0)}</span></div>
          <div class="chip" data-filter="idle"><span class="chip-dot" style="background:var(--amber)"></span>Idle <span class="count">{summary.get("idle",0)}</span></div>
          <div class="chip" data-filter="low_battery"><span class="chip-dot" style="background:var(--red)"></span>Low Battery <span class="count">{summary.get("low_battery",0)}</span></div>
          <div class="chip" data-filter="offline"><span class="chip-dot" style="background:var(--gray)"></span>Offline <span class="count">{summary.get("offline",0)}</span></div>
        </div>

        <div id="map"></div>

        <!-- Legend overlay (bottom-left, no overlap) -->
        <div class="map-overlay map-legend-card">
          <div class="map-legend-card-title">Legend</div>
          <div class="legend-item"><span class="legend-dot" style="background:var(--green)"></span>Active</div>
          <div class="legend-item"><span class="legend-dot" style="background:var(--amber)"></span>Idle</div>
          <div class="legend-item"><span class="legend-dot" style="background:var(--red)"></span>Low Battery</div>
          <div class="legend-item"><span class="legend-dot" style="background:var(--gray)"></span>Offline</div>
        </div>
      </div>

      <div class="panel device-panel">
        <div class="panel-tabs">
          <div class="panel-tab active">Devices</div>
          <div class="panel-tab" style="margin-left:auto;color:var(--text-2)" id="deviceCountTab">{total} units</div>
        </div>
        <div class="device-search">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.35-4.35"/></svg>
          <input id="deviceSearch" placeholder="Filter devices…" autocomplete="off">
        </div>
        <div class="device-list" id="deviceList"></div>
      </div>
    </div>

    <!-- Bottom row: Activity + Status dist + Battery dist -->
    <div class="bottom-row">
      <div class="panel">
        <div class="panel-head">
          <div class="panel-title">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            Recent Activity
          </div>
          <div style="font-size:11px;color:var(--text-3)">Last 8 events</div>
        </div>
        <div class="activity-list" id="activityList"></div>
      </div>

      <div class="panel">
        <div class="panel-head">
          <div class="panel-title">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/></svg>
            Status Distribution
          </div>
        </div>
        <div class="status-dist" id="statusDist"></div>
      </div>

      <div class="panel">
        <div class="panel-head">
          <div class="panel-title">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><rect x="2" y="7" width="18" height="10" rx="2"/><line x1="22" y1="11" x2="22" y2="13"/></svg>
            Battery Distribution
          </div>
          <div style="font-size:11px;color:var(--text-3)">Reporting units</div>
        </div>
        <div class="batt-dist" id="battDist"></div>
      </div>
    </div>

    <div class="footnote">
      Generated <code>{generated_at}</code> · Built with Python stdlib · OpenStreetMap data © contributors
    </div>
  </main>
</div>

<script src="{MAPLIBRE_JS}"></script>
<script>
  // ===== Embedded data =====
  const DEVICES = {devices_json};
  const ACTIVITY = {activity_json};
  const STATUS_CFG = {status_config_json};
  const NOW_EPOCH = {now_epoch};
  const CENTER = [{center_lon:.4f}, {center_lat:.4f}];  // MapLibre uses [lng, lat]

  // ===== Helpers =====
  function colorFor(status) {{ return (STATUS_CFG[status] || STATUS_CFG['unknown']).color; }}
  function labelFor(status) {{ return (STATUS_CFG[status] || STATUS_CFG['unknown']).label; }}

  function timeAgo(epoch) {{
    if (!epoch) return 'Unknown';
    const now = Math.floor(Date.now() / 1000);
    const diff = now - epoch;
    if (diff < 0) return 'future';
    if (diff < 60) return diff + 's ago';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
  }}

  function escHtml(s) {{
    return String(s).replace(/[&<>\"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}})[c]);
  }}

  // ===== 3D Map setup (MapLibre GL JS) =====
  const map = new maplibregl.Map({{
    container: 'map',
    style: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
    center: CENTER,
    zoom: 3.6,
    pitch: 45,
    bearing: -12,
    antialias: true,
    attributionControl: {{ compact: true }}
  }});

  // Navigation controls (zoom + compass + pitch reset)
  map.addControl(new maplibregl.NavigationControl({{ visualizePitch: true, showCompass: true, showZoom: true }}), 'top-right');
  map.addControl(new maplibregl.ScaleControl({{ unit: 'metric', maxWidth: 100 }}), 'bottom-right');
  map.addControl(new maplibregl.FullscreenControl(), 'top-right');

  // Add 3D building extrusion when style loads
  map.on('style.load', () => {{
    const layers = map.getStyle().layers || [];
    const buildingLayer = layers.find(l => l.id === 'building' || l.id === 'buildings' || (l['source-layer'] && l['source-layer'] === 'building'));
    if (buildingLayer && !map.getLayer('3d-buildings')) {{
      try {{
        map.addLayer({{
          id: '3d-buildings',
          source: buildingLayer.source,
          'source-layer': buildingLayer['source-layer'],
          type: 'fill-extrusion',
          minzoom: 13,
          paint: {{
            'fill-extrusion-color': '#2f3d5c',
            'fill-extrusion-height': [
              'interpolate', ['linear'], ['zoom'],
              13, 0,
              15.5, ['coalesce', ['get', 'render_height'], ['get', 'height'], 10]
            ],
            'fill-extrusion-base': 0,
            'fill-extrusion-opacity': 0.85
          }}
        }});
      }} catch (e) {{ console.warn('3D buildings unavailable:', e); }}
    }}
    // Update pitch indicator
    updatePitchIndicator();
  }});

  // ===== Custom HTML markers =====
  const markers = {{}};
  function buildMarkerEl(d) {{
    const color = colorFor(d.status);
    const isCritical = (d.status === 'low_battery');
    const wrap = document.createElement('div');
    wrap.className = 'marker-wrap';
    wrap.innerHTML = `<div class="pin ${{isCritical ? 'critical' : ''}}" style="background:${{color}};color:${{color}}"></div>`;
    return wrap;
  }}
  function buildPopupHtml(d) {{
    const color = colorFor(d.status);
    const batt = d.battery !== null ? d.battery + '%' : 'N/A';
    return `
      <b>${{escHtml(d.name)}}</b><br>
      <span style="color:var(--text-3);font-size:11.5px;font-family:'JetBrains Mono',monospace">${{escHtml(d.id)}}</span>
      <div style="margin-top:8px;display:flex;gap:6px;align-items:center">
        <span style="width:8px;height:8px;border-radius:50%;background:${{color}};display:inline-block;box-shadow:0 0 8px ${{color}}"></span>
        <span style="font-weight:600;color:${{color}}">${{labelFor(d.status)}}</span>
      </div>
      <div style="margin-top:8px;color:var(--text-2);font-size:11.5px;line-height:1.7">
        <div>Battery: <b style="color:var(--text-0)">${{batt}}</b></div>
        <div>Location: <b style="color:var(--text-0)">${{escHtml(d.location)}}</b></div>
        <div>Last seen: ${{escHtml(d.last_seen)}}</div>
      </div>`;
  }}

  DEVICES.forEach(d => {{
    if (!d.has_coords) return;
    const popup = new maplibregl.Popup({{ offset: 16, closeButton: true, maxWidth: '260px' }})
      .setHTML(buildPopupHtml(d));
    const m = new maplibregl.Marker({{ element: buildMarkerEl(d), anchor: 'center' }})
      .setLngLat([d.lon, d.lat])
      .setPopup(popup)
      .addTo(map);
    markers[d.id] = m;
  }});

  // Fit to bounds if any
  const valid = DEVICES.filter(d => d.has_coords);
  if (valid.length > 1) {{
    const bounds = new maplibregl.LngLatBounds();
    valid.forEach(d => bounds.extend([d.lon, d.lat]));
    map.fitBounds(bounds, {{ padding: 60, pitch: 45, bearing: -12, duration: 0 }});
  }}

  // ===== 3D toggle button =====
  let is3D = true;
  const toggle3DBtn = document.getElementById('toggle3D');
  toggle3DBtn.classList.add('active');
  toggle3DBtn.addEventListener('click', () => {{
    is3D = !is3D;
    if (is3D) {{
      map.easeTo({{ pitch: 45, bearing: -12, duration: 700 }});
      toggle3DBtn.classList.add('active');
      toggle3DBtn.querySelector('span').textContent = '3D';
    }} else {{
      map.easeTo({{ pitch: 0, bearing: 0, duration: 700 }});
      toggle3DBtn.classList.remove('active');
      toggle3DBtn.querySelector('span').textContent = '2D';
    }}
  }});

  // Reset view button (in topbar)
  const resetBtn = document.getElementById('resetView');
  if (resetBtn) {{
    resetBtn.addEventListener('click', () => {{
      if (valid.length > 1) {{
        const bounds = new maplibregl.LngLatBounds();
        valid.forEach(d => bounds.extend([d.lon, d.lat]));
        map.fitBounds(bounds, {{ padding: 60, pitch: 45, bearing: -12, duration: 1000 }});
      }} else {{
        map.flyTo({{ center: CENTER, zoom: 3.6, pitch: 45, bearing: -12 }});
      }}
    }});
  }}

  // Pitch indicator updates as user tilts
  function updatePitchIndicator() {{
    const p = Math.round(map.getPitch());
    const b = Math.round(map.getBearing());
    document.getElementById('pitchInd').textContent = (p > 5 ? '3D · ' : '2D · ') + p + '°' + (b !== 0 ? ' / ' + b + '°' : '');
  }}
  map.on('pitch', updatePitchIndicator);
  map.on('rotate', updatePitchIndicator);

  // ===== Filter & search state =====
  let activeFilter = 'all';
  let searchQuery = '';

  function deviceMatches(d) {{
    if (activeFilter !== 'all' && d.status !== activeFilter) return false;
    if (searchQuery) {{
      const q = searchQuery.toLowerCase();
      if (!(d.id.toLowerCase().includes(q)
        || d.name.toLowerCase().includes(q)
        || d.location.toLowerCase().includes(q)
        || labelFor(d.status).toLowerCase().includes(q))) return false;
    }}
    return true;
  }}

  function applyFilters() {{
    let visible = 0;
    DEVICES.forEach(d => {{
      const m = markers[d.id];
      if (!m) return;
      const el = m.getElement();
      if (deviceMatches(d)) {{ el.style.display = ''; visible++; }}
      else {{ el.style.display = 'none'; }}
    }});
    document.getElementById('mapCount').textContent = visible + ' plotted';
    renderDeviceList();
  }}

  // ===== Filter chips =====
  document.querySelectorAll('#filterChips .chip').forEach(chip => {{
    chip.addEventListener('click', () => {{
      document.querySelectorAll('#filterChips .chip').forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      activeFilter = chip.dataset.filter;
      applyFilters();
    }});
  }});

  // ===== Search inputs =====
  function onSearch(v) {{ searchQuery = v.trim(); applyFilters(); }}
  document.getElementById('deviceSearch').addEventListener('input', e => onSearch(e.target.value));
  document.getElementById('globalSearch').addEventListener('input', e => {{
    document.getElementById('deviceSearch').value = e.target.value;
    onSearch(e.target.value);
  }});

  // ===== Device list rendering =====
  function vehicleIcon() {{
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 17h2l1-6h12l1 6h2"/><circle cx="7" cy="17" r="1.5"/><circle cx="17" cy="17" r="1.5"/></svg>`;
  }}

  function renderDeviceList() {{
    const order = {{ active: 0, idle: 1, low_battery: 2, offline: 3, unknown: 4 }};
    const filtered = DEVICES.filter(deviceMatches).sort((a, b) => (order[a.status] - order[b.status]));
    const list = document.getElementById('deviceList');
    document.getElementById('deviceCountTab').textContent = filtered.length + ' units';
    if (filtered.length === 0) {{
      list.innerHTML = '<div class="device-empty">No devices match.</div>';
      return;
    }}
    list.innerHTML = filtered.map(d => {{
      const color = colorFor(d.status);
      const batt = d.battery !== null ? d.battery + '%' : 'N/A';
      const battColor = d.battery === null ? 'var(--text-3)' : (d.battery <= 15 ? 'var(--red)' : (d.battery <= 40 ? 'var(--amber)' : 'var(--green)'));
      const ago = timeAgo(d.last_seen_epoch);
      const noGps = !d.has_coords ? '<span style="color:var(--amber);font-size:10px;margin-left:4px">⚠ NO GPS</span>' : '';
      return `
        <div class="device-card" data-id="${{d.id}}">
          <div class="device-icon">
            ${{vehicleIcon()}}
            <span class="device-icon-dot" style="background:${{color}}"></span>
          </div>
          <div class="device-main">
            <div class="device-name">${{escHtml(d.name)}}</div>
            <div class="device-sub">
              <span style="font-family:'JetBrains Mono',monospace;color:var(--text-2)">${{escHtml(d.id)}}</span>
              <span class="dot-sep"></span>
              <span>${{escHtml(d.location)}}</span>
              ${{noGps}}
            </div>
          </div>
          <div class="device-meta">
            <div class="device-batt" style="color:${{battColor}}">${{batt}}</div>
            <div class="device-time">${{ago}}</div>
          </div>
        </div>`;
    }}).join('');

    // Click → fly to marker (3D cinematic)
    list.querySelectorAll('.device-card').forEach(card => {{
      card.addEventListener('click', () => {{
        list.querySelectorAll('.device-card').forEach(c => c.classList.remove('selected'));
        card.classList.add('selected');
        const id = card.dataset.id;
        const m = markers[id];
        if (m) {{
          const ll = m.getLngLat();
          map.flyTo({{
            center: [ll.lng, ll.lat],
            zoom: 14.5,
            pitch: is3D ? 60 : 0,
            bearing: is3D ? -20 : 0,
            speed: 1.4,
            curve: 1.4,
            essential: true
          }});
          setTimeout(() => m.togglePopup(), 1200);
        }}
      }});
    }});
  }}

  // ===== Activity feed =====
  function renderActivity() {{
    const list = document.getElementById('activityList');
    if (ACTIVITY.length === 0) {{
      list.innerHTML = '<div class="device-empty">No recent activity.</div>';
      return;
    }}
    list.innerHTML = ACTIVITY.map(a => `
      <div class="activity-item">
        <div class="activity-bullet" style="background:${{a.color}}"></div>
        <div class="activity-text">
          <b>${{escHtml(a.name)}}</b> reported <b style="color:${{a.color}}">${{escHtml(a.label)}}</b>
          <div style="font-size:11px;color:var(--text-3);margin-top:2px">${{escHtml(a.location)}}</div>
        </div>
        <div class="activity-time">${{timeAgo(a.epoch)}}</div>
      </div>`).join('');
  }}

  // ===== Status distribution =====
  function renderStatusDist() {{
    const counts = {{}};
    Object.keys(STATUS_CFG).forEach(k => counts[k] = 0);
    DEVICES.forEach(d => counts[d.status] = (counts[d.status] || 0) + 1);
    const total = DEVICES.length || 1;
    const html = Object.keys(STATUS_CFG).map(status => {{
      const cfg = STATUS_CFG[status];
      const c = counts[status] || 0;
      const pct = (c / total) * 100;
      return `
        <div class="dist-row">
          <div class="dist-label"><span class="legend-dot" style="background:${{cfg.color}}"></span>${{cfg.label}}</div>
          <div class="dist-bar"><div class="dist-fill" style="width:${{pct}}%;background:${{cfg.color}}"></div></div>
          <div class="dist-count">${{c}}</div>
        </div>`;
    }}).join('');
    document.getElementById('statusDist').innerHTML = html;
  }}

  // ===== Battery distribution =====
  function renderBattDist() {{
    const bins = [0, 0, 0, 0, 0]; // 0-20, 20-40, 40-60, 60-80, 80-100
    DEVICES.forEach(d => {{
      if (d.battery === null) return;
      const idx = Math.min(4, Math.floor(d.battery / 20));
      bins[idx]++;
    }});
    const max = Math.max(...bins, 1);
    const labels = ['0-20', '20-40', '40-60', '60-80', '80-100'];
    const colors = ['var(--red)', 'var(--amber)', 'var(--amber)', 'var(--green)', 'var(--green)'];
    const binsHtml = bins.map((n, i) => `
      <div class="batt-bin" style="height:${{(n / max * 100)}}%;background:linear-gradient(180deg,${{colors[i]}},rgba(0,0,0,.2))">
        <div class="bin-tip">${{n}} units · ${{labels[i]}}%</div>
      </div>`).join('');
    const labelsHtml = labels.map(l => `<div class="batt-bin-label">${{l}}</div>`).join('');
    document.getElementById('battDist').innerHTML =
      `<div class="batt-bins">${{binsHtml}}</div><div class="batt-bin-labels">${{labelsHtml}}</div>`;
  }}

  // ===== Live clock =====
  function tickClock() {{
    const d = new Date();
    const pad = n => n.toString().padStart(2, '0');
    document.getElementById('clock').textContent =
      pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
  }}

  // ===== Init =====
  renderDeviceList();
  renderActivity();
  renderStatusDist();
  renderBattDist();
  tickClock();
  setInterval(tickClock, 1000);
  setInterval(() => {{ renderDeviceList(); renderActivity(); }}, 30000); // refresh "X ago" labels
</script>
</body>
</html>"""
    return html


def main():
    print(f"Reading {CSV_PATH} ...")
    devices = load_devices(CSV_PATH)
    print(f"  Loaded {len(devices)} devices.")

    now = datetime.now()

    # Report data quality issues
    for d in devices:
        issues = []
        if not d["has_coords"]:
            issues.append("invalid/missing GPS")
        if d["battery"] is None:
            issues.append("missing battery")
        if d["status"] == "unknown":
            issues.append(f"unrecognised status '{d['raw_status']}'")
        if d["dt"] and (d["dt"] - now).total_seconds() > 0:
            issues.append("future last_seen timestamp")
        if issues:
            print(f"  [WARN] {d['id']} ({d['name']}): {', '.join(issues)}")

    html = generate_html(devices, now)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Dashboard written to {OUT_PATH}")


if __name__ == "__main__":
    main()
