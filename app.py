#!/usr/bin/env python3
"""
Morocco Medical Dashboard — Streamlit
Consumes FastAPI at API_BASE (default: http://localhost:8000)
"""

import subprocess
import pandas as pd
import plotly.express as px
import requests
import streamlit as st

API_BASE = "http://localhost:8000"

# ── Clear stale progress on startup ───────────────────────────────────────
if "startup_done" not in st.session_state:
    from pathlib import Path as _SP
    import json as _sj
    # Reset stale progress file only
    _pf = _SP("data/scraping_progress.json")
    if _pf.exists():
        _pd = _sj.loads(_pf.read_text())
        if not _pd.get("done", True):
            _pd["done"] = True
            _pf.write_text(_sj.dumps(_pd))
    st.session_state["startup_done"] = True

# ── Auto-start API if not running ──────────────────────────────────────────
def _ensure_api():
    try:
        requests.get(f"{API_BASE}/stats", timeout=2)
    except Exception:
        import sys
        subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "api:app", "--port", "8000"],
            cwd="."
        )
        import time
        for _ in range(10):
            time.sleep(1)
            try:
                requests.get(f"{API_BASE}/stats", timeout=1)
                break
            except Exception:
                continue

_ensure_api()

st.set_page_config(page_title="Morocco Medical Analytics", page_icon="🩺", layout="wide")

st.markdown("""
<style>
.main { background-color: #f8f9fa; }
.stMetric { background-color: #fff; padding: 15px; border-radius: 10px; box-shadow: 0 2px 6px rgba(0,0,0,.06); }
h1, h2, h3 { color: #1b2746; }
.stTabs [aria-selected="true"] { background-color: #0096d6 !important; color: white !important; }
</style>
""", unsafe_allow_html=True)


# ── API helpers ────────────────────────────────────────────────────────────

@st.cache_data(ttl=10)
def api_get(path: str, params: dict = None):
    try:
        r = requests.get(f"{API_BASE}{path}", params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        return None
    except Exception:
        return None


def require_api():
    r = api_get("/stats")
    if r is None:
        st.error("❌ API non disponible. Lancez d'abord :")
        st.code("uvicorn api:app --reload --port 8000")
        st.stop()
    return r


# ── Sidebar ────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🩺 DabaDoc Analytics")
    st.markdown("---")

    # ── URL Input → Pipeline Trigger (professor requirement)
    st.subheader("🔗 Source de données")
    data_url = st.text_input(
        "URL du dataset médical",
        value="https://www.dabadoc.com/recherche",
        help="Entrez l'URL de la source médicale à scraper"
    )
    # Default pages = last scraped page
    try:
        import json as _jd
        from pathlib import Path as _Pd
        _prog_data = _jd.loads(_Pd("data/scraping_progress.json").read_text())
        _last = _prog_data.get("total", 1297) if _prog_data.get("phase") != "enrich" else 1297
    except Exception:
        _last = 1297

    col_pages, col_btn = st.columns([1, 1])
    pages_end = col_pages.number_input("Total pages", min_value=1, max_value=1297, value=_last, step=10)

    if col_btn.button("▶ Lancer", use_container_width=True):
        if data_url:
            # Reset progress immediately before scraper starts
            from pathlib import Path as _PP
            import json as _jj
            _PP("data/scraping_progress.json").write_text(
                _jj.dumps({"current": 0, "total": pages_end, "doctors": 0, "done": False})
            )
            import threading, sys
            def _run_scraper():
                subprocess.run(
                    [sys.executable, "scraper_dabadoc.py",
                     "--pages", "1", str(pages_end), "--resume"],
                    cwd="."
                )
            threading.Thread(target=_run_scraper, daemon=True).start()
            st.success("✅ Scraper lancé!")
        else:
            st.warning("Entrez une URL valide.")

    # Stop button — kills scraper if running
    try:
        import psutil as _ps
        _scraper_procs = [
            p for p in _ps.process_iter(["pid", "cmdline"])
            if p.info["cmdline"] and "scraper_dabadoc" in " ".join(p.info["cmdline"])
        ]
        if _scraper_procs:
            if st.button("⏹ Stop Scraper", type="primary"):
                for p in _scraper_procs:
                    p.kill()
                from pathlib import Path as _P2
                import json as _j2
                _pf = _P2("data/scraping_progress.json")
                if _pf.exists():
                    _d = _j2.loads(_pf.read_text())
                    _d["done"] = True
                    _pf.write_text(_j2.dumps(_d))
                st.warning("🛑 Scraper arrêté.")
                st.rerun()
    except Exception:
        pass

    # ── Real-time scraping progress ────────────────────────────────────────
    import json as _json
    from pathlib import Path as _Path
    _prog_file = _Path("data/scraping_progress.json")
    if _prog_file.exists():
        try:
            _prog = _json.loads(_prog_file.read_text())
            _pct  = _prog["current"] / max(_prog["total"], 1)
            if _prog["done"]:
                st.success(f"✅ Scraping terminé — {_prog['doctors']} médecins collectés")
                if st.button("🔬 Enrichir adresses manquantes"):
                    import threading, sys, json as _je
                    from pathlib import Path as _PE
                    _PE("data/scraping_progress.json").write_text(
                        _je.dumps({"current": 0, "total": 1, "doctors": _prog["doctors"], "done": False, "phase": "enrich"})
                    )
                    def _run_enrich():
                        subprocess.run([sys.executable, "scraper_dabadoc.py", "--enrich-missing"], cwd=".")
                    threading.Thread(target=_run_enrich, daemon=True).start()
                    st.success("✅ Enrichissement lancé!")
                if st.button("🧹 Lancer Clean + DQV"):
                    import sys
                    proc2 = subprocess.run([sys.executable, "clean_data.py"], capture_output=True, text=True, cwd=".")
                    if proc2.returncode == 0:
                        st.success("✅ Clean terminé!")
                        st.cache_data.clear()
                    else:
                        st.error(proc2.stdout[-800:] + proc2.stderr[-800:])
            else:
                phase = _prog.get("phase", "scrape")
                if phase == "enrich":
                    _pct = _prog["current"] / max(_prog["total"], 1)
                    st.markdown("**🔬 Enrichissement en cours…**")
                    st.progress(_pct, text=f"Profil {_prog['current']} / {_prog['total']} enrichis")
                else:
                    st.markdown("**⏳ Scraping en cours…**")
                    st.progress(_pct, text=f"Page {_prog['current']} / {_prog['total']} — {_prog['doctors']} médecins")
                st.caption("La page se rafraîchit automatiquement.")
        except Exception:
            pass

    st.markdown("---")
    st.info("Source: DabaDoc.com — Maroc")
    st.caption(f"API: `{API_BASE}`")

    # Auto-refresh every 3s while scraping is running
    try:
        import json as _j
        from pathlib import Path as _P
        import psutil as _ps
        _prog_file = _P("data/scraping_progress.json")
        if _prog_file.exists():
            _p = _j.loads(_prog_file.read_text())
            _scraper_running = any(
                "scraper_dabadoc" in " ".join(proc.cmdline())
                for proc in _ps.process_iter(["cmdline"])
                if proc.info["cmdline"]
            )
            # If progress says running but scraper is dead → mark as done
            if not _p.get("done", True) and not _scraper_running:
                _p["done"] = True
                _prog_file.write_text(_j.dumps(_p))
            elif not _p.get("done", True) and _scraper_running:
                import time as _t
                _t.sleep(3)
                st.rerun()
    except Exception:
        pass

# ── Main ───────────────────────────────────────────────────────────────────
st.title("🩺 Morocco Medical Data Intelligence")
st.caption("Pipeline DabaDoc — FastAPI + Streamlit")
st.markdown("---")

stats = require_api()

# ── KPIs ───────────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Médecins",   stats["total_medecins"])
c2.metric("Villes Couvertes", stats["total_villes"])
c3.metric("Spécialités",      stats["total_specialites"] or "—")
c4.metric("Total Avis",       f"{stats['total_avis']:,}" if stats["total_avis"] else "—")

# ── Tabs ───────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5 = st.tabs(["🔍 Données", "📍 Carte", "📊 Analyse", "💡 Opportunités", "🤖 ML Saturation"])

# ── Tab 1: Données ─────────────────────────────────────────────────────────
with tab1:
    st.subheader("Base de données médicale")

    villes_data = api_get("/villes") or []
    specs_data  = api_get("/specialites") or []
    villes_list = ["Toutes"] + [v["ville"] for v in villes_data]
    specs_list  = ["Toutes"] + [s["specialite"] for s in specs_data]

    f1, f2, f3 = st.columns([2, 2, 1])
    sel_ville = f1.selectbox("Ville", villes_list, key="d_ville")
    sel_spec  = f2.selectbox("Spécialité", specs_list, key="d_spec")

    # Reset page to 1 when filters change
    filter_key = f"{sel_ville}_{sel_spec}"
    if st.session_state.get("_last_filter") != filter_key:
        st.session_state["_last_filter"] = filter_key
        st.session_state["_cur_page"] = 1

    # Get total first to show max pages
    _params_count = {"page": 1, "limit": 1}
    if sel_ville != "Toutes": _params_count["ville"] = sel_ville
    if sel_spec  != "Toutes": _params_count["specialite"] = sel_spec
    _total = (api_get("/medecins", _params_count) or {}).get("total", 0)
    _max_page = max(1, -(-_total // 50))

    sel_page = f3.number_input("Page", min_value=1, max_value=_max_page,
                               value=st.session_state.get("_cur_page", 1))
    st.session_state["_cur_page"] = sel_page

    params = {"page": sel_page, "limit": 50}
    if sel_ville != "Toutes": params["ville"] = sel_ville
    if sel_spec  != "Toutes": params["specialite"] = sel_spec

    result = api_get("/medecins", params) or {"total": 0, "data": []}
    df = pd.DataFrame(result["data"])

    st.caption(f"{result['total']} médecins trouvés — page {sel_page} / {_max_page}")

    if not df.empty:
        col_cfg = {}
        if "profile_url" in df.columns:
            col_cfg["profile_url"] = st.column_config.LinkColumn("Profil")
        if "nb_avis" in df.columns:
            col_cfg["nb_avis"] = st.column_config.NumberColumn("Avis", format="%d ⭐")
        for c in ["consultation_cabinet", "consultation_video", "consultation_domicile"]:
            if c in df.columns:
                col_cfg[c] = st.column_config.CheckboxColumn(c.replace("consultation_", "").title())
        st.dataframe(df, use_container_width=True, column_config=col_cfg)
        all_params = {"page": 1, "limit": _total}
        if sel_ville != "Toutes": all_params["ville"] = sel_ville
        if sel_spec  != "Toutes": all_params["specialite"] = sel_spec
        all_data = api_get("/medecins", all_params) or {"data": []}
        df_all = pd.DataFrame(all_data["data"])

        parts = []
        if sel_ville != "Toutes": parts.append(sel_ville)
        if sel_spec  != "Toutes": parts.append(sel_spec)
        fname = "medecins_" + ("_".join(parts) if parts else "tous") + ".csv"

        st.download_button(
            label=f"⬇️ Télécharger tout ({_total} médecins)",
            data=df_all.to_csv(index=False).encode("utf-8"),
            file_name=fname.replace(" ", "_"),
            mime="text/csv",
        )
    else:
        st.info("Aucun résultat.")

# ── Tab 2: Carte ───────────────────────────────────────────────────────────
with tab2:
    st.subheader("📍 Carte des Médecins")

    villes_data = api_get("/villes") or []
    specs_data  = api_get("/specialites") or []

    f1, f2 = st.columns(2)
    sel_ville_m = f1.selectbox("Ville", ["Toutes"] + [v["ville"] for v in villes_data], key="m_ville")
    sel_spec_m  = f2.selectbox("Spécialité", ["Toutes"] + [s["specialite"] for s in specs_data], key="m_spec")

    map_params = {}
    if sel_ville_m != "Toutes": map_params["ville"] = sel_ville_m
    if sel_spec_m  != "Toutes": map_params["specialite"] = sel_spec_m

    carte_data = api_get("/carte", map_params)

    if carte_data is None:
        st.info("GPS non disponible. Re-lancez le scraper avec `--deep-scrape`.")
    elif len(carte_data) == 0:
        st.warning("Aucun médecin avec GPS pour ces filtres.")
    else:
        df_map = pd.DataFrame(carte_data)
        st.caption(f"{len(df_map)} médecins géolocalisés")
        color_col = "specialite_clean" if "specialite_clean" in df_map.columns else "ville"
        fig = px.scatter_map(
            df_map, lat="latitude", lon="longitude",
            hover_name="nom_professionnel",
            hover_data={c: True for c in ["specialite_clean", "ville", "adresse_complete", "nb_avis"] if c in df_map.columns},
            color=color_col,
            zoom=5, height=550,
            map_style="open-street-map",
        )
        st.plotly_chart(fig, use_container_width=True)

    # City bar chart
    st.markdown("---")
    st.subheader("🏙️ Médecins par Ville (Top 15)")
    villes_df = pd.DataFrame(villes_data).head(15)
    if not villes_df.empty:
        fig_v = px.bar(villes_df, x="ville", y="nb_medecins", color="nb_medecins", color_continuous_scale="Blues")
        st.plotly_chart(fig_v, use_container_width=True)

# ── Tab 3: Analyse ─────────────────────────────────────────────────────────
with tab3:
    st.header("📊 Analyse")

    specs_df = pd.DataFrame(specs_data).head(12)

    a1, a2 = st.columns(2)
    with a1:
        st.subheader("Répartition par Spécialité")
        if not specs_df.empty:
            fig_s = px.pie(specs_df, values="nb_medecins", names="specialite",
                           color_discrete_sequence=px.colors.sequential.Blues_r, hole=0.35)
            st.plotly_chart(fig_s, use_container_width=True)

    with a2:
        st.subheader("Top 10 — Plus évalués")
        top_params = {"limit": 10, "page": 1}
        if sel_ville_m != "Toutes": top_params["ville"] = sel_ville_m
        top_data = api_get("/medecins", top_params)
        if top_data and top_data["data"]:
            df_top = pd.DataFrame(top_data["data"])
            if "nb_avis" in df_top.columns:
                df_top = df_top.nlargest(10, "nb_avis")[["nom_professionnel", "specialite_clean", "ville", "nb_avis"]]
                st.dataframe(df_top, use_container_width=True)

# ── Tab 4: Opportunités ────────────────────────────────────────────────────
with tab4:
    st.header("💡 Gaps — Zones sans Concurrence")
    st.markdown("Trouvez les quartiers d'une ville sans médecin pour votre spécialité.")

    villes_data2 = api_get("/villes") or []
    specs_data2  = api_get("/specialites") or []

    g1, g2 = st.columns(2)
    sel_gville = g1.selectbox("Ville", [v["ville"] for v in villes_data2], key="g_ville")
    sel_gspec  = g2.selectbox("Spécialité", [s["specialite"] for s in specs_data2], key="g_spec")

    if st.button("🔍 Analyser les gaps"):
        gaps = api_get("/gaps", {"ville": sel_gville, "specialite": sel_gspec})
        if gaps:
            st.metric("Quartiers sans concurrence", gaps["total_gaps"])
            if gaps["quartiers_sans_concurrence"]:
                st.success("Zones d'opportunité :")
                cols = st.columns(3)
                for i, q in enumerate(gaps["quartiers_sans_concurrence"]):
                    cols[i % 3].write(f"📍 {q}")
            else:
                st.info("Marché saturé dans tous les quartiers connus.")


# ── Tab 5: ML Saturation ───────────────────────────────────────────────────
with tab5:
    st.header("🤖 Prédiction de Saturation — ML")
    st.markdown("Estimez si une zone médicale est **saturée** ou une **opportunité** d'installation.")

    from pathlib import Path as _Path
    MODEL_PATH  = _Path("models/saturation_model.pkl")
    REPORT_PATH = _Path("models/saturation_report.json")

    # Train button
    if not MODEL_PATH.exists():
        st.warning("⚠️ Modèle non entraîné.")
        if st.button("🏋️ Entraîner le modèle"):
            with st.spinner("Entraînement en cours…"):
                import sys
                result = subprocess.run([sys.executable, "model.py"], capture_output=True, text=True)
                if result.returncode == 0:
                    st.success("✅ Modèle entraîné!")
                    st.code(result.stdout)
                    st.rerun()
                else:
                    st.error(result.stderr)
        st.stop()

    # Model report
    import json as _json
    report = _json.loads(REPORT_PATH.read_text())

    m1, m2, m3 = st.columns(3)
    m1.metric("Accuracy",  f"{report['accuracy']:.1%}")
    m2.metric("AUC-ROC",   f"{report['auc_roc']:.3f}" if report.get("auc_roc") else "—")
    m3.metric("F1 Macro",  f"{report['f1_macro']:.3f}")

    # Feature importance chart
    st.markdown("---")
    st.subheader("📊 Feature Importance")
    fi = report["feature_importance"]
    fi_df = pd.DataFrame({"Feature": list(fi.keys()), "Importance": list(fi.values())})
    fig_fi = px.bar(fi_df, x="Importance", y="Feature", orientation="h",
                    color="Importance", color_continuous_scale="Blues")
    fig_fi.update_layout(yaxis={"categoryorder": "total ascending"}, height=350)
    st.plotly_chart(fig_fi, use_container_width=True)

    # Prediction form
    st.markdown("---")
    st.subheader("🔮 Prédire une Zone")
    villes_list_ml = [v["ville"] for v in (api_get("/villes") or [])]
    specs_list_ml  = [s["specialite"] for s in (api_get("/specialites") or [])]

    p1, p2 = st.columns(2)
    pred_ville = p1.selectbox("Ville", villes_list_ml, key="ml_ville")
    pred_spec  = p2.selectbox("Spécialité", specs_list_ml, key="ml_spec")

    # Get quartiers for selected ville
    med_data = api_get("/medecins", {"ville": pred_ville, "limit": 500}) or {"data": []}
    quartiers = sorted(set(r.get("quartier_clean", "") for r in med_data["data"] if r.get("quartier_clean")))
    pred_quartier = st.selectbox("Quartier", quartiers or ["Autre/Inconnu"], key="ml_quartier")

    if st.button("🔮 Prédire la saturation"):
        try:
            from model import predict_zone
            result = predict_zone(pred_ville, pred_spec, pred_quartier)
            if "error" in result:
                st.warning(result["error"])
            else:
                score = result["saturation_score"]
                label = result["label"]
                st.markdown(f"### {label}")
                st.progress(score)
                st.metric("Score de saturation", f"{score:.1%}",
                          delta="Risque élevé" if score >= 0.5 else "Bonne opportunité",
                          delta_color="inverse")
        except Exception as e:
            st.error(f"Erreur: {e}")

    # Batch: saturation scores for all specialties in selected ville
    st.markdown("---")
    st.subheader(f"📋 Saturation globale — {pred_ville}")
    if st.button("📊 Analyser toutes les spécialités"):
        try:
            from model import predict_zone
            rows = []
            for spec in specs_list_ml:
                r = predict_zone(pred_ville, spec, "Autre/Inconnu")
                if "error" not in r:
                    rows.append(r)
            if rows:
                df_scores = pd.DataFrame(rows).sort_values("saturation_score", ascending=False)
                fig_scores = px.bar(df_scores, x="specialite", y="saturation_score",
                                    color="saturation_score", color_continuous_scale="RdYlGn_r",
                                    labels={"saturation_score": "Score Saturation", "specialite": "Spécialité"})
                fig_scores.add_hline(y=0.5, line_dash="dash", line_color="red", annotation_text="Seuil saturation")
                st.plotly_chart(fig_scores, use_container_width=True)
        except Exception as e:
            st.error(f"Erreur: {e}")
