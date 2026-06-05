#!/usr/bin/env python3
"""
Morocco Medical Dashboard — Streamlit
Consumes FastAPI at API_BASE (default: http://localhost:8000)
"""

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

API_BASE = "http://localhost:8000"

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

@st.cache_data(ttl=60)
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
    st.info("Source: DabaDoc.com — Maroc")
    st.caption(f"API: `{API_BASE}`")

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
tab1, tab2, tab3, tab4 = st.tabs(["🔍 Données", "📍 Carte", "📊 Analyse", "💡 Opportunités"])

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
    sel_page  = f3.number_input("Page", min_value=1, value=1, key="d_page")

    params = {"page": sel_page, "limit": 50}
    if sel_ville != "Toutes": params["ville"] = sel_ville
    if sel_spec  != "Toutes": params["specialite"] = sel_spec

    result = api_get("/medecins", params) or {"total": 0, "data": []}
    df = pd.DataFrame(result["data"])

    st.caption(f"{result['total']} médecins trouvés — page {sel_page}")

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
