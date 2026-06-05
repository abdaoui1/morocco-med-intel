#!/usr/bin/env python3
"""
Morocco Medical Data — FastAPI REST API
=======================================
Run: uvicorn api:app --reload --port 8000
Docs: http://localhost:8000/docs
"""

from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Morocco Medical API",
    description="REST API sur les données médicales DabaDoc — Maroc",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

CLEAN_PATH    = Path("data/processed/dabadoc_clean.csv")
ANALYTICS_PATH = Path("data/processed/dabadoc_analytics.csv")


def load_df() -> pd.DataFrame:
    if not CLEAN_PATH.exists():
        raise HTTPException(status_code=503, detail="Data not available. Run clean_data.py first.")
    return pd.read_csv(CLEAN_PATH)


def load_analytics() -> pd.DataFrame:
    if not ANALYTICS_PATH.exists():
        raise HTTPException(status_code=503, detail="Analytics data not available.")
    return pd.read_csv(ANALYTICS_PATH)


# ── Endpoints ──────────────────────────────────────────────────────────────

@app.get("/stats", summary="KPIs globaux")
def get_stats():
    df = load_df()
    return {
        "total_medecins": len(df),
        "total_villes":   int(df["ville"].nunique()),
        "total_specialites": int(df["specialite_clean"].nunique()) if "specialite_clean" in df.columns else None,
        "total_avis":     int(df["nb_avis"].sum()) if "nb_avis" in df.columns else None,
        "avec_gps":       int(df["latitude"].notna().sum()) if "latitude" in df.columns else None,
    }


@app.get("/medecins", summary="Liste des médecins (paginée + filtres)")
def get_medecins(
    ville:      Optional[str] = Query(None, description="Filtrer par ville"),
    specialite: Optional[str] = Query(None, description="Filtrer par spécialité (clean)"),
    page:       int = Query(1, ge=1),
    limit:      int = Query(50, ge=1, le=500),
):
    df = load_df()
    if ville:
        df = df[df["ville"].str.lower() == ville.lower()]
    if specialite:
        df = df[df["specialite_clean"].str.lower() == specialite.lower()]

    total = len(df)
    start = (page - 1) * limit
    df_page = df.iloc[start: start + limit]

    return {
        "total": total,
        "page":  page,
        "limit": limit,
        "data":  df_page.fillna("").astype(object).to_dict(orient="records"),
    }


@app.get("/villes", summary="Liste des villes + nombre de médecins")
def get_villes():
    df = load_df()
    counts = df["ville"].value_counts().reset_index()
    counts.columns = ["ville", "nb_medecins"]
    return counts.to_dict(orient="records")


@app.get("/specialites", summary="Liste des spécialités + nombre de médecins")
def get_specialites():
    df = load_analytics()
    col = "specialite_clean" if "specialite_clean" in df.columns else "specialite"
    counts = df[col].value_counts().reset_index()
    counts.columns = ["specialite", "nb_medecins"]
    return counts.to_dict(orient="records")


@app.get("/carte", summary="Points GPS pour la carte (lat, lon, infos)")
def get_carte(
    ville:      Optional[str] = Query(None),
    specialite: Optional[str] = Query(None),
):
    df = load_df()
    if "latitude" not in df.columns:
        raise HTTPException(status_code=404, detail="GPS data not available. Re-run scraper with --deep-scrape.")

    df = df.dropna(subset=["latitude", "longitude"])
    df["latitude"]  = pd.to_numeric(df["latitude"],  errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df = df.dropna(subset=["latitude", "longitude"])

    if ville:
        df = df[df["ville"].str.lower() == ville.lower()]
    if specialite:
        df = df[df["specialite_clean"].str.lower() == specialite.lower()]

    cols = ["nom_professionnel", "specialite_clean", "ville", "quartier_clean",
            "adresse_complete", "nb_avis", "latitude", "longitude"]
    cols = [c for c in cols if c in df.columns]
    return df[cols].fillna("").to_dict(orient="records")


@app.get("/gaps", summary="Quartiers sans médecin pour une spécialité donnée")
def get_gaps(
    ville:      str = Query(..., description="Ville cible"),
    specialite: str = Query(..., description="Spécialité cible"),
):
    df = load_df()
    df_a = load_analytics()
    spec_col = "specialite_clean" if "specialite_clean" in df_a.columns else "specialite"

    all_q  = set(df[df["ville"].str.lower() == ville.lower()]["quartier_clean"].unique())
    occ_q  = set(
        df_a[
            (df_a["ville"].str.lower() == ville.lower()) &
            (df_a[spec_col].str.lower() == specialite.lower())
        ]["quartier_clean"].unique()
    )
    gaps = sorted(all_q - occ_q)
    return {
        "ville": ville,
        "specialite": specialite,
        "quartiers_sans_concurrence": gaps,
        "total_gaps": len(gaps),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
