"""
generate_gap_chart.py — Génère une image propre des gaps pour le rapport
Usage: python generate_gap_chart.py --ville Casablanca --specialite Pédiatre
"""
import argparse
import unicodedata
import pandas as pd
import plotly.graph_objects as go
from pathlib import Path

def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFD', str(text)) if unicodedata.category(c) != 'Mn').lower().strip()

# Quartiers valides connus (filtre les noms d'adresses mal parsés)
KNOWN_QUARTIERS = {
    "2 Mars", "Agdal", "Ain Chock", "Ain Sebaa", "Ain Taoujtate",
    "Al Qods", "Alsace Lorraine", "Anfa", "Atlas", "Belvédère",
    "Bernoussi", "Bourgogne", "California", "Centre Ville",
    "Derb Sultan", "El Fida", "Errahma", "Gauthier", "Guéliz",
    "Hay Amal", "Hay El Oulfa", "Hay Hassani", "Hay Inara",
    "Hay Mohammadi", "Hay Nahda", "Hay Riad", "Hay Salama",
    "Hivernage", "Inezgane", "Les Hôpitaux", "Maarif", "Massira",
    "Mellah", "Mers Sultan", "Oasis", "Palmier", "Racine",
    "Route El Jadida", "Sbata", "Sidi Abderrahman", "Sidi Maarouf",
    "Sidi Moumen", "Sidi Othmane", "Témara", "Abdelmoumen",
    "Hay Oulfa", "Mazola", "Diour Jamaa", "Akkari",
}

def run(ville, specialite, out_path):
    df   = pd.read_csv("data/processed/dabadoc_clean.csv")
    df_a = pd.read_csv("data/processed/dabadoc_analytics.csv")
    spec_col = "specialite_clean" if "specialite_clean" in df_a.columns else "specialite"

    all_q = set(df[df["ville"] == ville]["quartier_clean"].unique()) - {"Autre/Inconnu"}

    # Match specialite accent-insensitive
    spec_match = df_a[spec_col].apply(normalize) == normalize(specialite)
    occ_q = set(
        df_a[(df_a["ville"] == ville) & spec_match]["quartier_clean"].unique()
    ) - {"Autre/Inconnu"}

    # Resolve exact specialite name for title
    spec_label = df_a[spec_match][spec_col].iloc[0] if spec_match.any() else specialite

    gaps = sorted((all_q - occ_q) & KNOWN_QUARTIERS)  # only clean quartier names

    # Nb médecins dans chaque quartier gap (toutes spécialités — montre la densité générale)
    q_counts = (
        df[df["ville"] == ville]
        .groupby("quartier_clean").size()
        .reset_index(name="nb_medecins")
    )
    q_counts = q_counts[q_counts["quartier_clean"].isin(gaps)].sort_values("nb_medecins", ascending=True)

    fig = go.Figure(go.Bar(
        x=q_counts["nb_medecins"],
        y=q_counts["quartier_clean"],
        orientation="h",
        marker_color="#e74c3c",
        text=q_counts["nb_medecins"],
        textposition="outside",
    ))

    fig.update_layout(
        title=dict(
            text=f"💡 Opportunités — {spec_label} à {ville}<br>"
                 f"<sup>{len(gaps)} quartiers sans {spec_label} (nb total médecins dans le quartier)</sup>",
            font_size=16,
        ),
        xaxis_title="Nb médecins (toutes spécialités) dans le quartier",
        yaxis_title="",
        plot_bgcolor="white",
        paper_bgcolor="white",
        height=max(400, len(gaps) * 35 + 150),
        width=800,
        margin=dict(l=160, r=80, t=100, b=60),
        font=dict(family="Arial", size=13),
        xaxis=dict(gridcolor="#eee"),
    )

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    fig.write_image(out_path, scale=2)
    print(f"✅ Image sauvegardée → {out_path}")
    print(f"   {len(gaps)} gaps : {gaps}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--ville",      default="Casablanca")
    p.add_argument("--specialite", default="Pédiatre")
    p.add_argument("--out",        default="data/viz/gaps_rapport.png")
    args = p.parse_args()
    run(args.ville, args.specialite, args.out)
