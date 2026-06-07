#!/usr/bin/env python3
"""Full project audit tests"""
import sys, json, subprocess
from pathlib import Path

results = []

def ok(msg): results.append(("✅", msg)); print(f"  ✅ {msg}")
def fail(msg): results.append(("❌", msg)); print(f"  ❌ {msg}")
def warn(msg): results.append(("⚠️", msg)); print(f"  ⚠️  {msg}")

# ══════════════════════════════════════════════════════════
print("\n━━━ 1. SCRAPER ━━━")
try:
    from scraper_dabadoc import make_session, fetch, parse_search_page, parse_profile_page, Doctor, SEARCH_URL, _DABADOC_IP
    ok("imports OK")
    ok(f"DNS bypass IP: {_DABADOC_IP}")

    s = make_session()
    html = fetch(s, SEARCH_URL.format(page=1))
    if html and len(html) > 5000:
        ok(f"fetch page 1: {len(html)} chars")
        docs = parse_search_page(html)
        if docs:
            ok(f"parse_search_page: {len(docs)} doctors")
            d = docs[0]
            if d.nom_professionnel: ok(f"  nom: {d.nom_professionnel}")
            else: fail("nom_professionnel empty")
            if d.ville: ok(f"  ville: {d.ville}")
            else: fail("ville empty")
            if d.profile_url: ok(f"  profile_url: present")
            else: warn("profile_url missing")
        else:
            fail("parse_search_page: 0 doctors")
    else:
        fail(f"fetch failed or blocked")
except Exception as e:
    fail(f"scraper error: {e}")

# ══════════════════════════════════════════════════════════
print("\n━━━ 2. PROFILE PARSE ━━━")
try:
    s2 = make_session()
    html2 = fetch(s2, "https://www.dabadoc.com/ma/diabetologue/agadir/brahim-boufous")
    if html2:
        doc = parse_profile_page(html2, Doctor(nom_professionnel="Dr Brahim Boufous"))
        if doc.adresse_complete: ok(f"adresse: {doc.adresse_complete[:60]}")
        else: fail("adresse_complete empty on profile with data")
        if doc.latitude: ok(f"GPS: {doc.latitude}, {doc.longitude}")
        else: warn("GPS not found")
        ok(f"nb_avis: {doc.nb_avis}")

        # Test contamination fix
        html3 = fetch(s2, "https://www.dabadoc.com/ma/medecin-generaliste/agadir/maria-rachami")
        doc3 = parse_profile_page(html3, Doctor(nom_professionnel="Maria Rachami"))
        if doc3.adresse_complete is None:
            ok("card-similar-doctor fix: no contamination")
        else:
            warn(f"Possible contamination: {doc3.adresse_complete}")
    else:
        fail("profile fetch failed")
except Exception as e:
    fail(f"profile parse error: {e}")

# ══════════════════════════════════════════════════════════
print("\n━━━ 3. DATA FILES ━━━")
import pandas as pd
for path, label in [
    ("data/raw/dabadoc_raw.csv", "raw"),
    ("data/processed/dabadoc_clean.csv", "clean"),
    ("data/processed/dabadoc_analytics.csv", "analytics"),
    ("data/processed/dabadoc_modeling.csv", "modeling"),
]:
    p = Path(path)
    if p.exists():
        df = pd.read_csv(p)
        ok(f"{label}: {len(df)} rows, {len(df.columns)} cols")
    else:
        fail(f"{label}: FILE NOT FOUND")

# ══════════════════════════════════════════════════════════
print("\n━━━ 4. CLEAN_DATA PIPELINE ━━━")
try:
    result = subprocess.run(
        [sys.executable, "clean_data.py"],
        capture_output=True, text=True, cwd=".", timeout=120
    )
    if result.returncode == 0:
        if "DQV GATE OPENED" in result.stdout:
            ok("DQV Gate: OPENED")
        elif "DQV GATE CLOSED" in result.stdout:
            fail("DQV Gate: CLOSED")
        if "Pipeline complete" in result.stdout:
            ok("Pipeline: complete")
        # Check for FAIL lines
        fails = [l for l in result.stdout.split("\n") if "❌ FAIL" in l]
        for f in fails: fail(f.strip())
    else:
        fail(f"clean_data.py exited {result.returncode}")
        print(result.stderr[-300:])
except Exception as e:
    fail(f"clean_data error: {e}")

# ══════════════════════════════════════════════════════════
print("\n━━━ 5. MODEL ━━━")
try:
    from model import train, predict_zone
    ok("model.py imports OK")

    model, report = train()
    ok(f"train: accuracy={report['accuracy']:.3f}, auc={report.get('auc_roc','N/A')}")
    ok(f"features used: {report['features_used']}")

    # Test predict
    pred = predict_zone("Casablanca", "Généraliste", "Maarif")
    if "error" not in pred:
        ok(f"predict_zone: score={pred['saturation_score']} {pred['label']}")
    else:
        warn(f"predict_zone: {pred['error']}")
except Exception as e:
    fail(f"model error: {e}")

# ══════════════════════════════════════════════════════════
print("\n━━━ 6. API ━━━")
try:
    import requests as req
    # Start API
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api:app", "--port", "8765", "--log-level", "error"],
        cwd="."
    )
    import time; time.sleep(3)

    endpoints = ["/stats", "/villes", "/specialites", "/medecins?page=1&limit=5",
                 "/carte", "/gaps?ville=Casablanca&specialite=Généraliste"]
    for ep in endpoints:
        try:
            r = req.get(f"http://localhost:8765{ep}", timeout=5)
            if r.status_code == 200:
                data = r.json()
                size = len(data) if isinstance(data, list) else len(str(data))
                ok(f"GET {ep}: 200 ({size} items/chars)")
            else:
                fail(f"GET {ep}: {r.status_code}")
        except Exception as e:
            fail(f"GET {ep}: {e}")
    proc.terminate()
except Exception as e:
    fail(f"API error: {e}")

# ══════════════════════════════════════════════════════════
print("\n━━━ 7. STREAMLIT APP ━━━")
try:
    import streamlit
    ok(f"streamlit version: {streamlit.__version__}")
    import plotly
    ok(f"plotly version: {plotly.__version__}")
    # Check px.scatter_map exists (new API)
    import plotly.express as px
    if hasattr(px, "scatter_map"):
        ok("px.scatter_map: available")
    elif hasattr(px, "scatter_mapbox"):
        warn("px.scatter_map not found — only scatter_mapbox available (older plotly)")
    # Try importing app without running it
    import ast
    app_src = Path("app.py").read_text(encoding="utf-8")
    ast.parse(app_src)
    ok("app.py: syntax OK")
except Exception as e:
    fail(f"app error: {e}")

# ══════════════════════════════════════════════════════════
print("\n" + "="*50)
print("AUDIT SUMMARY")
print("="*50)
ok_count   = sum(1 for r in results if r[0] == "✅")
fail_count = sum(1 for r in results if r[0] == "❌")
warn_count = sum(1 for r in results if r[0] == "⚠️")
print(f"  ✅ {ok_count} passed")
print(f"  ❌ {fail_count} failed")
print(f"  ⚠️  {warn_count} warnings")
if fail_count == 0:
    print("\n🎉 PROJET OK — prêt pour soutenance!")
else:
    print("\n🔧 PROBLEMS FOUND:")
    for icon, msg in results:
        if icon == "❌": print(f"  → {msg}")
