#!/usr/bin/env python3
"""
Morocco Medical Intelligence — Streamlit Dashboard
Tableau de bord d'intelligence médicale territoriale à l'échelle des villes marocaines.
"""

import io
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ── Config ────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Morocco Medical Intelligence",
    page_icon="🩺",
    layout="wide",
)

CLEAN_PATH = Path("data/processed/dabadoc_clean.csv")
POP_PATH   = Path("data/external/population_villes.csv")

# Seuils OMS par 10 000 habitants
OMS_SEUILS = {
    "Généraliste":            10.0,
    "Cardiologue":             0.5,
    "Pédiatre":                1.2,
    "Gynécologue":             0.8,
    "Ophtalmologue":           0.4,
    "Dentiste":                3.0,
    "Dermatologue":            0.3,
    "Radiologue":              0.3,
    "Chirurgien":              0.3,
    "Psychiatre/Psychologue":  0.3,
}
OMS_DEFAULT = 0.3

# ── Chargement des données ─────────────────────────────────────────────────────

@st.cache_data
def load_data():
    if not CLEAN_PATH.exists():
        return None, None
    df = pd.read_csv(CLEAN_PATH)
    df["ville"] = df["ville"].str.strip().str.title()
    df["specialite_clean"] = df["specialite_clean"].str.strip()

    df_pop = pd.read_csv(POP_PATH)
    df_pop["ville"] = df_pop["ville"].str.strip().str.title()
    return df, df_pop


# ── Calcul des indicateurs ─────────────────────────────────────────────────────

@st.cache_data
def compute_indices(df: pd.DataFrame, df_pop: pd.DataFrame):
    """Calcule ISM, IOE, Shannon, RGS pour chaque ville/spécialité."""

    counts = (
        df.groupby(["ville", "specialite_clean"])
        .size()
        .reset_index(name="nb_medecins")
    )
    counts["ville"] = counts["ville"].str.strip().str.title()

    merged = counts.merge(df_pop, on="ville", how="left")
    merged["population_2024"] = merged["population_2024"].fillna(0)

    # ── A. ISM ────────────────────────────────────────────────────────────────
    merged["ism"] = merged.apply(
        lambda r: r["nb_medecins"] / (r["population_2024"] / 10_000)
        if r["population_2024"] > 0 else 0,
        axis=1,
    )

    # ── B. IOE ────────────────────────────────────────────────────────────────
    def norm(series):
        mn, mx = series.min(), series.max()
        if mx == mn:
            return pd.Series([0.5] * len(series), index=series.index)
        return (series - mn) / (mx - mn)

    merged["pib_norm"]        = norm(merged["pib_par_hab_index"].fillna(0))
    merged["croissance_norm"] = norm(merged["croissance_demo"].fillna(0))

    for spec in merged["specialite_clean"].unique():
        mask = merged["specialite_clean"] == spec
        merged.loc[mask, "ism_norm"] = norm(merged.loc[mask, "ism"]).values

    merged["ioe"] = (
        merged["pib_norm"] * 0.4
        + (1 - merged["ism_norm"]) * 0.4
        + merged["croissance_norm"] * 0.2
    )

    def ioe_badge(v):
        if v >= 0.70: return "Élevé"
        if v >= 0.50: return "Moyen"
        if v >= 0.35: return "Modéré"
        return "Saturé"

    merged["ioe_badge"] = merged["ioe"].apply(ioe_badge)

    # ── C. Déserts médicaux ───────────────────────────────────────────────────
    merged["seuil_oms"] = merged["specialite_clean"].map(
        lambda s: OMS_SEUILS.get(s, OMS_DEFAULT)
    )
    merged["desert"] = (
        (merged["population_2024"] > 150_000)
        & ((merged["nb_medecins"] == 0) | (merged["ism"] < 0.1))
    )

    # ── D. Shannon ────────────────────────────────────────────────────────────
    shannon_rows = []
    for ville, grp in df.groupby("ville"):
        if len(grp) == 0:
            continue
        props = grp["specialite_clean"].value_counts(normalize=True)
        h = -sum(p * math.log(p) for p in props if p > 0)
        shannon_rows.append({"ville": ville, "shannon": h})
    df_shannon = pd.DataFrame(shannon_rows)

    # ── E. RGS ────────────────────────────────────────────────────────────────
    rgs_rows = []
    for ville, grp in df.groupby("ville"):
        gen  = (grp["specialite_clean"] == "Généraliste").sum()
        spec = (grp["specialite_clean"] != "Généraliste").sum()
        rgs  = gen / spec if spec > 0 else float("inf")
        rgs_rows.append({"ville": ville, "rgs": rgs, "nb_gen": gen, "nb_spec_total": spec})
    df_rgs = pd.DataFrame(rgs_rows)

    # Coordonnées GPS moyennes par ville
    gps_cols = [c for c in ["latitude", "longitude"] if c in df.columns]
    if gps_cols:
        df_gps = (
            df.dropna(subset=gps_cols)
            .groupby("ville")[gps_cols]
            .mean()
            .reset_index()
        )
    else:
        df_gps = pd.DataFrame(columns=["ville"] + gps_cols)

    return merged, df_shannon, df_rgs, df_gps


# ── Helpers UI ─────────────────────────────────────────────────────────────────

BADGE_COLOR = {
    "Élevé":  "#1D9E75",
    "Moyen":  "#BA7517",
    "Modéré": "#888888",
    "Saturé": "#D85A30",
}


def ism_color(ism, seuil):
    if ism >= seuil:        return "#1D9E75"
    if ism >= 0.5 * seuil: return "#BA7517"
    return "#D85A30"


def ism_statut(ism, seuil):
    if ism >= seuil:        return "Suffisant"
    if ism >= 0.5 * seuil: return "Insuffisant"
    return "Critique"


def shannon_label(h):
    if h > 2.5:  return "Élevée — offre bien diversifiée"
    if h >= 1.5: return "Moyenne"
    return "Faible — offre peu diversifiée"


def rgs_label(rgs):
    if rgs == float("inf") or rgs > 1: return "Orientée soins primaires"
    if rgs >= 0.5:                      return "Équilibrée"
    return "Sur-spécialisée"


def _to_csv_bytes(df: pd.DataFrame) -> bytes:
    """Encode un DataFrame en CSV utf-8-sig (compatible Excel)."""
    return df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")


# ── F1 — Génération PDF ────────────────────────────────────────────────────────

def generate_city_pdf(ville, pop_ville, nb_medecins, h_val, rgs_val,
                      nb_gen, nb_spe, df_opp):
    """Génère un rapport PDF professionnel pour la ville donnée. Retourne bytes ou None."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
        )
    except ImportError:
        return None

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "mmi_title", parent=styles["Title"],
        textColor=colors.HexColor("#1b2746"), fontSize=20, spaceAfter=6,
    )
    h2_style = ParagraphStyle(
        "mmi_h2", parent=styles["Heading2"],
        textColor=colors.HexColor("#0096d6"), fontSize=13,
        spaceBefore=12, spaceAfter=4,
    )

    story = []

    # En-tête
    story.append(Paragraph(f"Profil médical — {ville}", title_style))
    story.append(Paragraph(
        "Morocco Medical Intelligence · Données DabaDoc · RGPH 2024 HCP",
        styles["Italic"],
    ))
    story.append(HRFlowable(width="100%", thickness=2,
                             color=colors.HexColor("#0096d6")))
    story.append(Spacer(1, 0.4 * cm))

    # Indicateurs clés
    story.append(Paragraph("Indicateurs clés", h2_style))
    pop_str  = f"{pop_ville:,}" if pop_ville else "N/D"
    rgs_str  = f"{rgs_val:.2f}" if rgs_val != float("inf") else "∞"
    kpis = [
        ["Population (RGPH 2024)",         pop_str],
        ["Médecins recensés",              str(nb_medecins)],
        ["dont Généralistes",              str(nb_gen)],
        ["dont Spécialistes",              str(nb_spe)],
        ["Diversité Shannon (H)",          f"{h_val:.2f} → {shannon_label(h_val)}"],
        ["Ratio Généraliste/Spécialiste",  f"{rgs_str} → {rgs_label(rgs_val)}"],
    ]
    tbl_kpi = Table(kpis, colWidths=[8 * cm, 9 * cm])
    tbl_kpi.setStyle(TableStyle([
        ("BACKGROUND",     (0, 0), (0, -1), colors.HexColor("#e8f4fb")),
        ("TEXTCOLOR",      (0, 0), (0, -1), colors.HexColor("#1b2746")),
        ("FONTNAME",       (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE",       (0, 0), (-1, -1), 9),
        ("GRID",           (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1),
         [colors.white, colors.HexColor("#f4f9fc")]),
        ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",     (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 5),
    ]))
    story.append(tbl_kpi)
    story.append(Spacer(1, 0.5 * cm))

    # Top opportunités
    story.append(Paragraph("Top opportunités médicales", h2_style))
    opp_top = df_opp[df_opp["Écart"] > 0].head(10)
    if not opp_top.empty:
        header = [["Spécialité", "ISM ville", "ISM national", "Écart", "Statut"]]
        rows = [
            [str(r["Spécialité"]), str(r["ISM ville"]),
             str(r["ISM national moyen"]), str(r["Écart"]), str(r["Opportunité"])]
            for _, r in opp_top.iterrows()
        ]
        tbl_opp = Table(
            header + rows,
            colWidths=[4.5 * cm, 2.5 * cm, 3 * cm, 2.5 * cm, 4.5 * cm],
        )
        tbl_opp.setStyle(TableStyle([
            ("BACKGROUND",     (0, 0), (-1, 0), colors.HexColor("#0096d6")),
            ("TEXTCOLOR",      (0, 0), (-1, 0), colors.white),
            ("FONTNAME",       (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",       (0, 0), (-1, -1), 8.5),
            ("GRID",           (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#edfaf4")]),
            ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",     (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING",  (0, 0), (-1, -1), 4),
        ]))
        story.append(tbl_opp)
    else:
        story.append(Paragraph(
            "Aucune opportunité détectée pour cette ville.", styles["BodyText"],
        ))

    story.append(Spacer(1, 0.8 * cm))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.lightgrey))
    story.append(Paragraph(
        "<font size='8' color='grey'>Rapport généré par Morocco Medical Intelligence"
        " · Données DabaDoc · RGPH 2024 HCP</font>",
        styles["Normal"],
    ))

    doc.build(story)
    buf.seek(0)
    return buf.read()


# ── Vérification données ───────────────────────────────────────────────────────

if not CLEAN_PATH.exists():
    st.error("Données introuvables. Lance d'abord : python clean_data.py")
    st.stop()

df_raw, df_pop = load_data()
if df_raw is None:
    st.error("Données introuvables. Lance d'abord : python clean_data.py")
    st.stop()

df_ind, df_shannon, df_rgs, df_gps = compute_indices(df_raw, df_pop)

# Listes de référence
all_specs  = sorted(df_ind["specialite_clean"].unique())
all_villes = sorted(df_raw["ville"].unique())

# ── En-tête ────────────────────────────────────────────────────────────────────

st.title("🩺 Morocco Medical Intelligence")
st.caption("Intelligence médicale territoriale · Données DabaDoc · RGPH 2024 HCP")
st.markdown("---")

# ── Onglets (6) ────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "🇲🇦 Vue nationale",
    "📐 Suffisance (ISM)",
    "💼 Opportunités (IOE)",
    "🚨 Déserts médicaux",
    "🏙️ Profil ville",
    "🔀 Comparer des villes",
])

# ══════════════════════════════════════════════════════════════════════════════
# ONGLET 1 — Vue d'ensemble nationale
# ══════════════════════════════════════════════════════════════════════════════

with tab1:

    # ── F5 — Moteur de recherche ──────────────────────────────────────────────
    st.subheader("🔍 Recherche médecin")
    search_query = st.text_input(
        "Rechercher par nom, spécialité ou ville",
        placeholder="Ex : cardiologue Casablanca…",
        key="search_input",
    )
    if search_query.strip():
        q = search_query.strip().lower()
        search_cols = [c for c in ["nom_professionnel", "specialite_clean", "ville"]
                       if c in df_raw.columns]
        mask = df_raw[search_cols].apply(
            lambda col: col.str.lower().str.contains(q, na=False)
        ).any(axis=1)
        df_search = df_raw[mask].copy()
        disp_cols = [c for c in ["nom_professionnel", "specialite_clean", "ville",
                                  "adresse_complete", "profile_url", "source"]
                     if c in df_search.columns]
        st.caption(f"{len(df_search)} résultat(s) pour « {search_query} »")
        col_cfg_search = {}
        if "profile_url" in disp_cols:
            col_cfg_search["profile_url"] = st.column_config.LinkColumn("Profil DabaDoc")
        st.dataframe(df_search[disp_cols], use_container_width=True,
                     hide_index=True, column_config=col_cfg_search)
        st.download_button(
            label=f"⬇️ Télécharger les résultats ({len(df_search)})",
            data=_to_csv_bytes(df_search[disp_cols]),
            file_name=f"recherche_{q[:20].replace(' ', '_')}.csv",
            mime="text/csv",
            key="dl_search",
        )
        st.markdown("---")

    # ── KPIs ──────────────────────────────────────────────────────────────────
    total_medecins = len(df_raw)
    total_villes   = df_raw["ville"].nunique()
    ism_moyen      = df_ind["ism"].mean()
    deserts_count  = (
        df_ind[df_ind["desert"]]
        .groupby("ville").size().reset_index().shape[0]
    )

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total médecins recensés",     f"{total_medecins:,}")
    k2.metric("Villes couvertes",             f"{total_villes:,}")
    k3.metric("ISM moyen national",           f"{ism_moyen:.2f} / 10k hab.")
    k4.metric("Villes avec déserts médicaux", f"{deserts_count}")

    st.markdown("---")

    # ── Top 15 villes ─────────────────────────────────────────────────────────
    ville_counts = (
        df_raw.groupby("ville").size()
        .reset_index(name="nb_medecins")
        .sort_values("nb_medecins", ascending=False)
        .head(15)
    )
    fig_villes = px.bar(
        ville_counts,
        x="nb_medecins", y="ville", orientation="h",
        color="nb_medecins", color_continuous_scale="Blues",
        title="Top 15 villes par nombre de médecins",
        labels={"nb_medecins": "Nb médecins", "ville": ""},
    )
    fig_villes.update_layout(
        yaxis={"categoryorder": "total ascending"},
        coloraxis_showscale=False, height=450,
    )
    st.plotly_chart(fig_villes, use_container_width=True)

    col_donut, col_tree = st.columns(2)

    with col_donut:
        spec_counts = df_raw["specialite_clean"].value_counts().reset_index()
        spec_counts.columns = ["specialite", "nb"]
        top10  = spec_counts.head(10).copy()
        autres = spec_counts.iloc[10:]["nb"].sum()
        if autres > 0:
            top10 = pd.concat(
                [top10, pd.DataFrame([{"specialite": "Autres", "nb": autres}])],
                ignore_index=True,
            )
        fig_donut = px.pie(
            top10, values="nb", names="specialite", hole=0.4,
            title="Répartition par spécialité (top 10 + Autres)",
            color_discrete_sequence=px.colors.sequential.Blues_r,
        )
        fig_donut.update_traces(textposition="inside", textinfo="percent+label")
        st.plotly_chart(fig_donut, use_container_width=True)

    with col_tree:
        tree_data = (
            df_ind.groupby("ville")
            .agg(nb_medecins=("nb_medecins", "sum"), ism_moy=("ism", "mean"))
            .reset_index()
        )
        fig_tree = px.treemap(
            tree_data, path=["ville"], values="nb_medecins",
            color="ism_moy", color_continuous_scale="RdYlGn",
            title="Densité médicale par ville (taille = nb médecins, couleur = ISM moyen)",
            labels={"ism_moy": "ISM moyen"},
        )
        fig_tree.update_layout(height=420)
        st.plotly_chart(fig_tree, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# ONGLET 2 — Indice de Suffisance Médicale
# ══════════════════════════════════════════════════════════════════════════════

with tab2:
    st.subheader("Indice de Suffisance Médicale (ISM)")
    st.caption("ISM = nb médecins / (population / 10 000 hab.) · Comparé au seuil OMS de référence")

    sel_spec_ism = st.selectbox("Spécialité", all_specs, key="ism_spec")
    seuil = OMS_SEUILS.get(sel_spec_ism, OMS_DEFAULT)

    df_ism = (
        df_ind[df_ind["specialite_clean"] == sel_spec_ism]
        .merge(df_pop[["ville", "population_2024"]], on="ville",
               how="left", suffixes=("", "_pop"))
        .sort_values("ism", ascending=False)
    )
    if "population_2024_pop" in df_ism.columns:
        df_ism["population_2024"] = df_ism["population_2024"].fillna(
            df_ism["population_2024_pop"]
        )
        df_ism = df_ism.drop(columns=["population_2024_pop"])

    df_ism["couleur"] = df_ism["ism"].apply(lambda v: ism_color(v, seuil))

    fig_ism = go.Figure()
    fig_ism.add_trace(go.Bar(
        x=df_ism["ville"], y=df_ism["ism"],
        marker_color=df_ism["couleur"], name="ISM",
        text=df_ism["ism"].round(2), textposition="outside",
    ))
    fig_ism.add_hline(
        y=seuil, line_dash="dot", line_color="red",
        annotation_text=f"Seuil OMS recommandé ({seuil})",
        annotation_position="top right",
    )
    fig_ism.update_layout(
        title=f"Indice de Suffisance Médicale — {sel_spec_ism}",
        xaxis_title="Ville", yaxis_title="ISM (médecins / 10k hab.)",
        height=480, showlegend=False,
    )
    st.plotly_chart(fig_ism, use_container_width=True)

    # Tableau ISM
    df_ism_tbl = df_ism[["ville", "nb_medecins", "population_2024", "ism"]].copy()
    df_ism_tbl["Statut"] = df_ism_tbl["ism"].apply(lambda v: ism_statut(v, seuil))
    df_ism_tbl = df_ism_tbl.rename(columns={
        "ville": "Ville", "nb_medecins": "Nb médecins",
        "population_2024": "Population", "ism": "ISM",
    })
    df_ism_tbl["ISM"]        = df_ism_tbl["ISM"].round(3)
    df_ism_tbl["Population"] = df_ism_tbl["Population"].fillna(0).astype(int)
    df_ism_tbl = df_ism_tbl.sort_values("ISM", ascending=False).reset_index(drop=True)
    st.dataframe(df_ism_tbl, use_container_width=True, hide_index=True)

    # ── F3 — Export CSV ISM ───────────────────────────────────────────────────
    st.download_button(
        label="⬇️ Télécharger ce tableau (CSV)",
        data=_to_csv_bytes(df_ism_tbl),
        file_name=f"ISM_{sel_spec_ism.replace('/', '-')}.csv",
        mime="text/csv",
        key="dl_ism",
    )

    # ── F2 — Simulateur « Et si ? » ───────────────────────────────────────────
    st.markdown("---")
    st.subheader("🧮 Simulateur « Et si ? »")
    st.caption("Simulez l'impact de l'ajout de médecins sur l'ISM d'une ville")

    sim_villes_list = df_ism["ville"].tolist() if not df_ism.empty else all_villes
    sim_ville = st.selectbox("Ville à simuler", options=sim_villes_list, key="sim_ville")
    sim_nb    = st.slider(
        "Nombre de médecins à ajouter", min_value=1, max_value=200, value=10, step=1,
        key="sim_nb",
    )

    sim_row = df_ism[df_ism["ville"] == sim_ville]
    if not sim_row.empty:
        sim_pop      = float(sim_row["population_2024"].values[0])
        sim_current  = int(sim_row["nb_medecins"].values[0])
        sim_ism_now  = float(sim_row["ism"].values[0])
        sim_ism_proj = (sim_current + sim_nb) / (sim_pop / 10_000) if sim_pop > 0 else 0.0
        sim_manque   = max(0, math.ceil(seuil * sim_pop / 10_000) - sim_current)
        sim_progress = min(1.0, sim_ism_proj / seuil) if seuil > 0 else 0.0

        sc1, sc2, sc3 = st.columns(3)
        sc1.metric("ISM actuel",  f"{sim_ism_now:.3f}", delta="baseline")
        sc2.metric("ISM projeté", f"{sim_ism_proj:.3f}",
                   delta=f"+{sim_ism_proj - sim_ism_now:.3f}")
        sc3.metric("Médecins manquants (seuil OMS)", f"{sim_manque}")

        st.progress(
            sim_progress,
            text=f"Progression vers le seuil OMS ({sim_progress * 100:.0f} %)",
        )

        if sim_ism_proj >= seuil:
            st.success(
                f"✅ Avec +{sim_nb} médecin(s), {sim_ville} atteindrait le seuil OMS "
                f"({seuil} / 10k hab.) pour {sel_spec_ism}."
            )
        else:
            still_needed = max(
                0, math.ceil(seuil * sim_pop / 10_000) - (sim_current + sim_nb)
            )
            st.warning(
                f"⚠️ Il manquerait encore {still_needed} médecin(s) après l'ajout de {sim_nb} "
                f"pour atteindre le seuil OMS de {seuil} / 10k hab."
            )


# ══════════════════════════════════════════════════════════════════════════════
# ONGLET 3 — Indice d'Opportunité Économique
# ══════════════════════════════════════════════════════════════════════════════

with tab3:
    st.subheader("Indice d'Opportunité Économique (IOE)")
    st.caption(
        "IOE = 0.4 × PIB_norm + 0.4 × (1 − densité_norm) + 0.2 × croissance_norm  ·  "
        "Plus l'IOE est élevé, plus la ville est attractive pour s'installer"
    )

    sel_spec_ioe = st.selectbox("Spécialité", all_specs, key="ioe_spec")

    df_ioe = (
        df_ind[df_ind["specialite_clean"] == sel_spec_ioe]
        .sort_values("ioe", ascending=False)
        .reset_index(drop=True)
    )

    pop_ref = df_pop.set_index("ville")["population_2024"]
    df_ioe["population_plot"] = df_ioe["ville"].map(pop_ref).fillna(50_000)

    fig_ioe = px.scatter(
        df_ioe,
        x="ism", y="pib_par_hab_index",
        size="population_plot", color="ioe",
        text="ville", color_continuous_scale="RdYlGn", size_max=50,
        title=f"Opportunités économiques — {sel_spec_ioe}",
        labels={
            "ism": "ISM (concurrence médicale)",
            "pib_par_hab_index": "PIB par hab. (indice)",
            "ioe": "IOE",
        },
    )
    fig_ioe.update_traces(textposition="top center")
    fig_ioe.add_annotation(
        x=df_ioe["ism"].min(),
        y=df_ioe["pib_par_hab_index"].max() if "pib_par_hab_index" in df_ioe.columns else 90,
        text="Zone idéale : fort pouvoir d'achat + faible concurrence",
        showarrow=False,
        font=dict(color="#1D9E75", size=11),
        bgcolor="rgba(29,158,117,0.1)",
        bordercolor="#1D9E75",
        borderwidth=1,
    )
    fig_ioe.update_layout(height=500)
    st.plotly_chart(fig_ioe, use_container_width=True)

    df_ioe_tbl = df_ioe[[
        "ville", "ioe", "ioe_badge", "pib_par_hab_index", "ism", "croissance_demo"
    ]].copy()
    df_ioe_tbl = df_ioe_tbl.rename(columns={
        "ville": "Ville", "ioe": "IOE", "ioe_badge": "Potentiel",
        "pib_par_hab_index": "PIB index", "ism": f"ISM {sel_spec_ioe}",
        "croissance_demo": "Croissance démo (%)",
    })
    df_ioe_tbl["IOE"] = df_ioe_tbl["IOE"].round(3)
    df_ioe_tbl[f"ISM {sel_spec_ioe}"] = df_ioe_tbl[f"ISM {sel_spec_ioe}"].round(3)
    st.dataframe(df_ioe_tbl, use_container_width=True, hide_index=True)

    # ── F3 — Export CSV IOE ───────────────────────────────────────────────────
    st.download_button(
        label="⬇️ Télécharger ce tableau (CSV)",
        data=_to_csv_bytes(df_ioe_tbl),
        file_name=f"IOE_{sel_spec_ioe.replace('/', '-')}.csv",
        mime="text/csv",
        key="dl_ioe",
    )


# ══════════════════════════════════════════════════════════════════════════════
# ONGLET 4 — Déserts médicaux
# ══════════════════════════════════════════════════════════════════════════════

with tab4:
    st.subheader("Déserts médicaux")
    st.caption("Villes avec population > 150 000 hab. et ISM < 0.1 pour la spécialité sélectionnée")

    sel_spec_desert = st.selectbox("Spécialité", all_specs, key="desert_spec")
    seuil_d = OMS_SEUILS.get(sel_spec_desert, OMS_DEFAULT)

    df_desert_spec = df_ind[df_ind["specialite_clean"] == sel_spec_desert].copy()

    all_known_villes = df_pop.copy()
    all_known_villes["ville"] = all_known_villes["ville"].str.strip().str.title()
    df_desert_full = all_known_villes.merge(
        df_desert_spec[["ville", "nb_medecins", "ism", "desert"]],
        on="ville", how="left",
    )
    df_desert_full["nb_medecins"] = df_desert_full["nb_medecins"].fillna(0).astype(int)
    df_desert_full["ism"]         = df_desert_full["ism"].fillna(0)
    df_desert_full["desert"] = (
        (df_desert_full["population_2024"] > 150_000)
        & ((df_desert_full["nb_medecins"] == 0) | (df_desert_full["ism"] < 0.1))
    )

    def map_statut(row):
        if row["desert"]:          return "Désert médical"
        if row["ism"] < seuil_d:   return "Sous-couvert"
        return "Bien couvert"

    df_desert_full["statut_carte"] = df_desert_full.apply(map_statut, axis=1)

    df_map_desert = df_desert_full.merge(df_gps, on="ville", how="inner")

    if not df_map_desert.empty and "latitude" in df_map_desert.columns:
        color_map_d = {
            "Désert médical": "#D85A30",
            "Sous-couvert":   "#BA7517",
            "Bien couvert":   "#1D9E75",
        }
        fig_desert_map = px.scatter_map(
            df_map_desert,
            lat="latitude", lon="longitude",
            color="statut_carte", color_discrete_map=color_map_d,
            size="population_2024", size_max=40,
            zoom=5, center={"lat": 31.5, "lon": -7},
            map_style="open-street-map",
            hover_name="ville",
            hover_data={
                "population_2024": True, "nb_medecins": True,
                "ism": ":.3f", "statut_carte": True,
                "latitude": False, "longitude": False,
            },
            title=f"Couverture médicale — {sel_spec_desert}",
        )
        fig_desert_map.update_layout(height=520)
        st.plotly_chart(fig_desert_map, use_container_width=True)
    else:
        st.info("Coordonnées GPS insuffisantes pour afficher la carte.")

    df_tbl_d = df_desert_full[df_desert_full["desert"]].copy()
    df_tbl_d["manque_estime"] = df_tbl_d.apply(
        lambda r: max(0, math.ceil(seuil_d * r["population_2024"] / 10_000 - r["nb_medecins"])),
        axis=1,
    )
    df_tbl_d = df_tbl_d[["ville", "population_2024", "nb_medecins", "ism", "manque_estime"]].copy()
    df_tbl_d = df_tbl_d.rename(columns={
        "ville": "Ville", "population_2024": "Population",
        "nb_medecins": f"Nb {sel_spec_desert}s",
        "ism": "ISM", "manque_estime": "Manque estimé",
    })
    df_tbl_d["ISM"] = df_tbl_d["ISM"].round(3)
    df_tbl_d = df_tbl_d.sort_values("Population", ascending=False).reset_index(drop=True)

    if df_tbl_d.empty:
        st.success(
            f"Aucun désert médical détecté pour la spécialité **{sel_spec_desert}**"
            f" dans les villes > 150k hab."
        )
    else:
        st.markdown(f"**{len(df_tbl_d)} désert(s) médical(aux) détecté(s) pour {sel_spec_desert}**")
        st.dataframe(df_tbl_d, use_container_width=True, hide_index=True)

        # ── F3 — Export CSV Déserts ───────────────────────────────────────────
        st.download_button(
            label="⬇️ Télécharger ce tableau (CSV)",
            data=_to_csv_bytes(df_tbl_d),
            file_name=f"deserts_{sel_spec_desert.replace('/', '-')}.csv",
            mime="text/csv",
            key="dl_desert",
        )


# ══════════════════════════════════════════════════════════════════════════════
# ONGLET 5 — Profil ville
# ══════════════════════════════════════════════════════════════════════════════

with tab5:
    st.subheader("Profil ville")

    sel_ville = st.selectbox("Ville", all_villes, key="profil_ville")

    df_ville = df_raw[df_raw["ville"] == sel_ville]
    pop_row  = df_pop[df_pop["ville"] == sel_ville]
    pop_ville = int(pop_row["population_2024"].values[0]) if not pop_row.empty else None

    shannon_row = df_shannon[df_shannon["ville"] == sel_ville]
    h_val = float(shannon_row["shannon"].values[0]) if not shannon_row.empty else 0.0

    rgs_row = df_rgs[df_rgs["ville"] == sel_ville]
    rgs_val = float(rgs_row["rgs"].values[0])         if not rgs_row.empty else 0.0
    nb_gen  = int(rgs_row["nb_gen"].values[0])         if not rgs_row.empty else 0
    nb_spe  = int(rgs_row["nb_spec_total"].values[0])  if not rgs_row.empty else 0

    # Indicateurs calculés une seule fois, réutilisés par F6 et le reste
    ism_ville    = df_ind[df_ind["ville"] == sel_ville].set_index("specialite_clean")["ism"]
    ism_national = df_ind.groupby("specialite_clean")["ism"].mean()

    top3_specs = df_ville["specialite_clean"].value_counts().head(3).index.tolist()
    df_opp_pre = pd.DataFrame({
        "Spécialité": ism_national.index,
        "ISM national moyen": ism_national.values,
    })
    df_opp_pre["ISM ville"] = df_opp_pre["Spécialité"].map(ism_ville).fillna(0)
    df_opp_pre["Écart"]     = (df_opp_pre["ISM national moyen"] - df_opp_pre["ISM ville"]).round(3)
    top3_opp = (
        df_opp_pre[df_opp_pre["Écart"] > 0]
        .nlargest(3, "Écart")["Spécialité"].tolist()
    )

    # ── Fiche récap ───────────────────────────────────────────────────────────
    p1, p2, p3 = st.columns(3)
    p1.metric("Population", f"{pop_ville:,}" if pop_ville else "N/D")
    p2.metric("Total médecins", f"{len(df_ville):,}")
    p3.metric("Généralistes / Spécialistes", f"{nb_gen} / {nb_spe}")

    st.info(
        f"**Diversité de l'offre (Shannon):** H = {h_val:.2f} → {shannon_label(h_val)}  \n"
        f"**Ratio Généraliste/Spécialiste:** {rgs_val:.2f} → {rgs_label(rgs_val)}"
    )

    # ── F6 — Analyse IA ───────────────────────────────────────────────────────
    if st.button("🤖 Générer l'analyse IA", key="btn_ai"):
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            st.error(
                "Clé API manquante. Définissez la variable d'environnement ANTHROPIC_API_KEY."
            )
        else:
            try:
                import anthropic as _anthropic  # noqa: PLC0415

                pop_str_ai  = f"{pop_ville:,} habitants" if pop_ville else "non disponible"
                rgs_str_ai  = f"{rgs_val:.2f}" if rgs_val != float("inf") else "∞"
                top3s_str   = ", ".join(top3_specs) if top3_specs else "N/D"
                top3o_str   = ", ".join(top3_opp)  if top3_opp  else "Aucune"

                prompt = (
                    f"Tu es un expert en santé publique au Maroc. "
                    f"Voici les données médicales de la ville de {sel_ville} :\n"
                    f"- Population : {pop_str_ai}\n"
                    f"- Nombre total de médecins : {len(df_ville)}\n"
                    f"- Indice de Shannon (diversité) : {h_val:.2f} ({shannon_label(h_val)})\n"
                    f"- Ratio Généraliste/Spécialiste : {rgs_str_ai} ({rgs_label(rgs_val)})\n"
                    f"- Top 3 spécialités présentes : {top3s_str}\n"
                    f"- Top 3 opportunités détectées : {top3o_str}\n\n"
                    f"En 3 phrases professionnelles en français, synthétise le profil médical "
                    f"de {sel_ville} et recommande les meilleures spécialités pour s'y installer."
                )
                client = _anthropic.Anthropic(api_key=api_key)
                with st.spinner("Analyse en cours…"):
                    msg = client.messages.create(
                        model="claude-sonnet-4-6",
                        max_tokens=300,
                        messages=[{"role": "user", "content": prompt}],
                    )
                st.success("Analyse IA")
                st.markdown(f"> {msg.content[0].text}")
            except ImportError:
                st.error("Module `anthropic` non installé. Lancez : pip install anthropic")
            except Exception as exc:
                st.error(f"Erreur API Anthropic : {exc}")

    st.markdown("---")

    # ── ISM ville vs moyenne nationale ────────────────────────────────────────
    specs_commun = ism_ville.index.intersection(ism_national.index)
    if not specs_commun.empty:
        df_compare = pd.DataFrame({
            "Spécialité":        specs_commun,
            f"{sel_ville}":      ism_ville[specs_commun].values,
            "Moyenne nationale": ism_national[specs_commun].values,
        }).sort_values(f"{sel_ville}", ascending=True)

        fig_compare = go.Figure()
        fig_compare.add_trace(go.Bar(
            name="Moyenne nationale",
            y=df_compare["Spécialité"], x=df_compare["Moyenne nationale"],
            orientation="h", marker_color="#aaaaaa",
        ))
        fig_compare.add_trace(go.Bar(
            name=sel_ville,
            y=df_compare["Spécialité"], x=df_compare[f"{sel_ville}"],
            orientation="h", marker_color="#0096d6",
        ))
        fig_compare.update_layout(
            barmode="group",
            title=f"Couverture médicale — {sel_ville} vs Moyenne nationale",
            xaxis_title="ISM (médecins / 10k hab.)",
            height=max(350, len(specs_commun) * 30),
            legend=dict(orientation="h", y=1.05),
        )
        st.plotly_chart(fig_compare, use_container_width=True)
    else:
        st.info("Données insuffisantes pour cette ville.")

    # ── Tableau des opportunités ───────────────────────────────────────────────
    st.markdown("**Opportunités dans cette ville** (spécialités sous-représentées vs moyenne nationale)")

    df_opp_ville = df_opp_pre.copy()
    df_opp_ville["Nb médecins"] = df_opp_ville["Spécialité"].map(
        df_ind[df_ind["ville"] == sel_ville].set_index("specialite_clean")["nb_medecins"]
    ).fillna(0).astype(int)
    df_opp_ville["Opportunité"] = df_opp_ville["Écart"].apply(
        lambda e: "✅ Opportunité" if e > 0 else "—"
    )
    df_opp_ville["ISM national moyen"] = df_opp_ville["ISM national moyen"].round(3)
    df_opp_ville["ISM ville"]          = df_opp_ville["ISM ville"].round(3)
    df_opp_ville = df_opp_ville.sort_values("Écart", ascending=False).reset_index(drop=True)

    st.dataframe(df_opp_ville, use_container_width=True, hide_index=True)

    # ── F3 — Export CSV Profil ville ──────────────────────────────────────────
    st.download_button(
        label="⬇️ Télécharger les opportunités (CSV)",
        data=_to_csv_bytes(df_opp_ville),
        file_name=f"opportunites_{sel_ville.replace(' ', '_')}.csv",
        mime="text/csv",
        key="dl_profil",
    )

    # ── F1 — Export PDF ───────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("📄 Rapport PDF")
    if st.button("Générer le rapport PDF", key="btn_pdf"):
        pdf_bytes = generate_city_pdf(
            ville=sel_ville, pop_ville=pop_ville,
            nb_medecins=len(df_ville), h_val=h_val,
            rgs_val=rgs_val, nb_gen=nb_gen, nb_spe=nb_spe,
            df_opp=df_opp_ville,
        )
        if pdf_bytes is None:
            st.error("Module `reportlab` non installé. Lancez : pip install reportlab")
        else:
            st.download_button(
                label=f"⬇️ Télécharger le rapport PDF — {sel_ville}",
                data=pdf_bytes,
                file_name=f"rapport_{sel_ville.replace(' ', '_')}.pdf",
                mime="application/pdf",
                key="dl_pdf",
            )


# ══════════════════════════════════════════════════════════════════════════════
# ONGLET 6 — Comparer des villes
# ══════════════════════════════════════════════════════════════════════════════

with tab6:
    st.subheader("🔀 Comparer des villes")
    st.caption("Sélectionnez entre 2 et 5 villes pour comparer leurs indicateurs médicaux")

    default_comp = all_villes[:2] if len(all_villes) >= 2 else all_villes
    comp_villes = st.multiselect(
        "Villes à comparer",
        options=all_villes,
        default=default_comp,
        max_selections=5,
        key="comp_villes",
    )

    if len(comp_villes) < 2:
        st.warning("Sélectionnez au moins 2 villes pour la comparaison.")
    else:
        comp_rows = []
        for v in comp_villes:
            sh_row_c   = df_shannon[df_shannon["ville"] == v]
            rgs_row_c  = df_rgs[df_rgs["ville"] == v]
            ioe_moy_c  = df_ind[df_ind["ville"] == v]["ioe"].mean()
            ism_moy_c  = df_ind[df_ind["ville"] == v]["ism"].mean()
            h_c        = float(sh_row_c["shannon"].values[0]) if not sh_row_c.empty else 0.0
            rgs_c_raw  = float(rgs_row_c["rgs"].values[0]) if not rgs_row_c.empty else 0.0
            rgs_c      = min(rgs_c_raw, 5.0)  # cap à 5 pour normalisation radar
            pop_c_arr  = df_pop[df_pop["ville"] == v]["population_2024"].values
            pop_c      = int(pop_c_arr[0]) if len(pop_c_arr) > 0 else 0
            nb_c       = len(df_raw[df_raw["ville"] == v])
            comp_rows.append({
                "Ville":       v,
                "Population":  pop_c,
                "Nb médecins": nb_c,
                "ISM moyen":   round(ism_moy_c, 3),
                "IOE moyen":   round(ioe_moy_c, 3),
                "Shannon":     round(h_c, 3),
                "RGS":         round(rgs_c, 3),
            })
        df_comp = pd.DataFrame(comp_rows)

        # ── Radar chart ───────────────────────────────────────────────────────
        radar_indicators = ["ISM moyen", "IOE moyen", "Shannon", "RGS"]

        def _norm_radar(col_name):
            mn, mx = df_comp[col_name].min(), df_comp[col_name].max()
            if mx == mn:
                return pd.Series([0.5] * len(df_comp), index=df_comp.index)
            return (df_comp[col_name] - mn) / (mx - mn)

        df_radar = df_comp.copy()
        for ind in radar_indicators:
            df_radar[ind + "_n"] = _norm_radar(ind)

        palette = px.colors.qualitative.Set2
        fig_radar = go.Figure()
        for idx, row in df_radar.iterrows():
            vals = [float(row[ind + "_n"]) for ind in radar_indicators]
            vals += vals[:1]
            cats = radar_indicators + [radar_indicators[0]]
            fig_radar.add_trace(go.Scatterpolar(
                r=vals, theta=cats, fill="toself",
                name=str(row["Ville"]),
                line_color=palette[int(idx) % len(palette)],
            ))
        fig_radar.update_layout(
            polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
            title="Comparaison radar — indicateurs normalisés (0–1)",
            showlegend=True, height=480,
        )
        st.plotly_chart(fig_radar, use_container_width=True)

        # ── Tableau comparatif ────────────────────────────────────────────────
        st.markdown("**Indicateurs bruts**")
        df_comp_disp = df_comp.copy()
        df_comp_disp["Population"] = df_comp_disp["Population"].apply(
            lambda x: f"{x:,}" if x > 0 else "N/D"
        )
        st.dataframe(df_comp_disp, use_container_width=True, hide_index=True)

        # ── F3 — Export CSV Comparaison ───────────────────────────────────────
        st.download_button(
            label="⬇️ Télécharger la comparaison (CSV)",
            data=_to_csv_bytes(df_comp),
            file_name="comparaison_villes.csv",
            mime="text/csv",
            key="dl_comp",
        )
