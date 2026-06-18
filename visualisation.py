"""
visualisation.py — EDA Dashboard
Génère des diagrammes pour comprendre la data DabaDoc Maroc
"""
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.io as pio
from pathlib import Path

df = pd.read_csv("data/processed/dabadoc_clean.csv")
Path("data/viz").mkdir(exist_ok=True)

# ── 1. Top 15 villes par nombre de médecins ───────────────────────────────
fig1 = px.bar(
    df["ville"].value_counts().head(15).reset_index(),
    x="ville", y="count",
    title="🏙️ Top 15 Villes — Nombre de Médecins",
    color="count", color_continuous_scale="Blues",
    labels={"count": "Nb médecins", "ville": "Ville"}
)
fig1.write_html("data/viz/01_villes.html")
print("✅ 01_villes.html")

# ── 2. Répartition par spécialité (pie) ──────────────────────────────────
spec_counts = df["specialite_clean"].value_counts().head(12)
fig2 = px.pie(
    values=spec_counts.values, names=spec_counts.index,
    title="🩺 Répartition par Spécialité",
    hole=0.4, color_discrete_sequence=px.colors.sequential.Blues_r
)
fig2.write_html("data/viz/02_specialites.html")
print("✅ 02_specialites.html")

# ── 3. Heatmap : spécialité × ville (top 10×10) ──────────────────────────
top_villes = df["ville"].value_counts().head(10).index
top_specs  = df["specialite_clean"].value_counts().head(10).index
heat = df[df["ville"].isin(top_villes) & df["specialite_clean"].isin(top_specs)]
pivot = heat.pivot_table(index="specialite_clean", columns="ville", aggfunc="size", fill_value=0)
fig3 = px.imshow(
    pivot, text_auto=True, aspect="auto",
    title="🔥 Heatmap Spécialité × Ville (Top 10)",
    color_continuous_scale="Blues"
)
fig3.write_html("data/viz/03_heatmap.html")
print("✅ 03_heatmap.html")

# ── 4. Répartition des quartiers par ville (top 5 villes) ────────────────
top5_villes = df["ville"].value_counts().head(5).index
df_q = df[df["ville"].isin(top5_villes)]
quartier_counts = df_q.groupby(["ville", "quartier_clean"]).size().reset_index(name="count")
quartier_counts = quartier_counts.sort_values("count", ascending=False)
fig4 = px.bar(
    quartier_counts.groupby("ville").head(5),
    x="quartier_clean", y="count", color="ville", barmode="group",
    title="🏘️ Top Quartiers par Ville (Top 5 villes)",
    labels={"count": "Nb médecins", "quartier_clean": "Quartier"}
)
fig4.write_html("data/viz/04_avis_boxplot.html")
print("✅ 04_avis_boxplot.html")

# ── 5. Sources DabaDoc vs med.ma ──────────────────────────────────────────
if "source" in df.columns:
    src_counts = df["source"].value_counts().reset_index()
    src_counts.columns = ["source", "count"]
    fig5 = px.pie(
        src_counts, values="count", names="source",
        title="📡 Sources des données",
        color_discrete_sequence=["#1f77b4", "#ff7f0e"]
    )
    fig5.write_html("data/viz/05_consultations.html")
    print("✅ 05_consultations.html")

# ── 6. Carte GPS des médecins ─────────────────────────────────────────────
df_gps = df.dropna(subset=["latitude","longitude"]).copy()
df_gps["latitude"]  = pd.to_numeric(df_gps["latitude"],  errors="coerce")
df_gps["longitude"] = pd.to_numeric(df_gps["longitude"], errors="coerce")
df_gps = df_gps.dropna(subset=["latitude","longitude"])
df_gps = df_gps[(df_gps["latitude"].between(27,36)) & (df_gps["longitude"].between(-14,-1))]

if not df_gps.empty:
    fig6 = px.scatter_map(
        df_gps, lat="latitude", lon="longitude",
        color="specialite_clean", hover_name="nom_professionnel",
        hover_data={"ville": True, "specialite_clean": True},
        zoom=5, height=600, map_style="open-street-map",
        title="📍 Carte GPS des Médecins au Maroc"
    )
    fig6.write_html("data/viz/06_carte_gps.html")
    print(f"✅ 06_carte_gps.html ({len(df_gps)} médecins géolocalisés)")

# ── 7. Top quartiers par densité (toutes villes)  ────────────────────────
q_counts = df["quartier_clean"].value_counts().head(15).reset_index()
q_counts.columns = ["quartier", "nb_medecins"]
q_counts = q_counts[q_counts["quartier"] != "Autre/Inconnu"]
fig7 = px.bar(
    q_counts, x="nb_medecins", y="quartier", orientation="h",
    color="nb_medecins", color_continuous_scale="Blues",
    title="🏘️ Top 15 Quartiers — Densité Médicale",
    labels={"nb_medecins": "Nb médecins", "quartier": ""}
)
fig7.update_layout(yaxis={"categoryorder": "total ascending"})
fig7.write_html("data/viz/07_top_medecins.html")
print("✅ 07_top_medecins.html")

# ── 8. Ratio médecins / ville (densité) ──────────────────────────────────
ville_counts = df["ville"].value_counts().reset_index()
ville_counts.columns = ["ville", "nb_medecins"]
fig8 = px.treemap(
    ville_counts.head(20), path=["ville"], values="nb_medecins",
    title="🗺️ Densité Médicale par Ville (Treemap)",
    color="nb_medecins", color_continuous_scale="Blues"
)
fig8.write_html("data/viz/08_treemap_villes.html")
print("✅ 08_treemap_villes.html")

print(f"\n✅ 8 diagrammes générés dans data/viz/")
print(f"   Total médecins: {len(df)}")
print(f"   Villes: {df['ville'].nunique()}")
print(f"   Spécialités: {df['specialite_clean'].nunique()}")
