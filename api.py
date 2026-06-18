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
        "avec_gps":       int(df["latitude"].notna().sum()) if "latitude" in df.columns else None,
        "avec_adresse":   int((df["adresse_complete"] != "Non spécifiée").sum()) if "adresse_complete" in df.columns else None,
    }


@app.get("/medecins", summary="Liste des médecins (paginée + filtres)")
def get_medecins(
    ville:      Optional[str] = Query(None, description="Filtrer par ville"),
    specialite: Optional[str] = Query(None, description="Filtrer par spécialité (clean)"),
    page:       int = Query(1, ge=1),
    limit:      int = Query(50, ge=1, le=50000),
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
            "adresse_complete", "latitude", "longitude"]
    cols = [c for c in cols if c in df.columns]
    return df[cols].fillna("").to_dict(orient="records")


@app.get("/opportunites", summary="Scoring opportunité par ville pour une spécialité")
def get_opportunites(
    specialite: str = Query(..., description="Spécialité cible"),
    min_total:  int = Query(50, description="Nb minimum de médecins dans la ville"),
):
    df = load_df()
    spec_col = "specialite_clean" if "specialite_clean" in df.columns else "specialite"

    total_par_ville = df.groupby("ville").size().rename("total")
    spec_df = df[df[spec_col].str.lower() == specialite.lower()]
    spec_par_ville = spec_df.groupby("ville").size().rename("nb_spec")

    result = total_par_ville.to_frame().join(spec_par_ville, how="left").fillna(0)
    result["nb_spec"] = result["nb_spec"].astype(int)

    # Filter villes significatives seulement
    result = result[result["total"] >= min_total]
    result["score_opportunite"] = (1 - result["nb_spec"] / result["total"]).round(4)

    # Sort: nb_spec ascending (moins de médecins = meilleure opportunité), total descending (villes importantes)
    result = result.reset_index().sort_values(["nb_spec", "total"], ascending=[True, False])

    return result.to_dict(orient="records")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
