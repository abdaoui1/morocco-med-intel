"""
merge.py — Fusion DabaDoc + med.ma
====================================
Input :  data/raw/dabadoc_raw.csv
         data/raw/medma_raw.csv
Output:  data/raw/merged_raw.csv

Logique de déduplication :
  - Clé unique = nom normalisé + ville normalisée
  - En cas de doublon : DabaDoc prioritaire pour profile_url/GPS
                        med.ma prioritaire pour adresse_complete (si DabaDoc vide)
"""

import re
import unicodedata
import pandas as pd
from pathlib import Path

DABADOC_RAW = Path("data/raw/dabadoc_raw.csv")
MEDMA_RAW   = Path("data/raw/medma_raw.csv")
MERGED_RAW  = Path("data/raw/merged_raw.csv")

FINAL_COLS = [
    "nom_professionnel", "profile_url", "specialite", "ville",
    "adresse_complete", "latitude", "longitude", "source",
]

def normalize(text: str) -> str:
    text = "".join(
        c for c in unicodedata.normalize("NFD", str(text))
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", text.lower().strip())


def run():
    if not DABADOC_RAW.exists():
        print(f"❌ {DABADOC_RAW} introuvable")
        return
    if not MEDMA_RAW.exists():
        print(f"❌ {MEDMA_RAW} introuvable — lance scraper_medma.py d'abord")
        return

    # Charger les deux sources
    df_daba  = pd.read_csv(DABADOC_RAW, dtype=str).fillna("")
    df_medma = pd.read_csv(MEDMA_RAW,   dtype=str).fillna("")

    df_daba["source"]  = "DabaDoc"
    df_medma["source"] = "med.ma"

    # Renommer adresse_brute → adresse_complete si nécessaire
    if "adresse_brute" in df_medma.columns and "adresse_complete" not in df_medma.columns:
        df_medma = df_medma.rename(columns={"adresse_brute": "adresse_complete"})

    print(f"📥 DabaDoc : {len(df_daba)} médecins")
    print(f"📥 med.ma  : {len(df_medma)} médecins")

    # Aligner les colonnes
    for col in FINAL_COLS:
        if col not in df_daba.columns:
            df_daba[col] = ""
        if col not in df_medma.columns:
            df_medma[col] = ""

    df_daba  = df_daba[FINAL_COLS]
    df_medma = df_medma[FINAL_COLS]

    # Clé de déduplication
    def dedup_key(row):
        return normalize(row["nom_professionnel"]) + "_" + normalize(row["ville"])

    df_daba["_key"]  = df_daba.apply(dedup_key, axis=1)
    df_medma["_key"] = df_medma.apply(dedup_key, axis=1)

    # Index DabaDoc par clé
    daba_index = df_daba.set_index("_key")

    enriched, new_count = 0, 0

    result_rows = []

    # 1. Parcourir DabaDoc — enrichir adresse depuis med.ma si vide
    medma_index = df_medma.set_index("_key")

    for key, row in daba_index.iterrows():
        row = row.copy()
        if not row["adresse_complete"].strip() or row["adresse_complete"].strip() == "Non spécifiée":
            if key in medma_index.index:
                medma_row = medma_index.loc[key]
                if isinstance(medma_row, pd.DataFrame):
                    medma_row = medma_row.iloc[0]
                addr = medma_row["adresse_complete"].strip()
                if addr:
                    # DabaDoc maha adresse → khud adresse + profile_url dyal med.ma
                    row["adresse_complete"] = addr
                    row["profile_url"]      = medma_row["profile_url"].strip()
                    row["source"]           = "med.ma"
                    enriched += 1
        result_rows.append(row)

    # 2. Ajouter les médecins med.ma qui ne sont PAS dans DabaDoc
    daba_keys = set(daba_index.index)
    for key, row in medma_index.iterrows():
        if key not in daba_keys:
            result_rows.append(row.copy())
            new_count += 1

    df_merged = pd.DataFrame(result_rows).reset_index(drop=True)
    df_merged = df_merged[FINAL_COLS]  # drop _key

    # Déduplication finale
    df_merged["_key"] = df_merged.apply(dedup_key, axis=1)
    df_merged = df_merged.drop_duplicates(subset=["_key"], keep="first").drop(columns=["_key"])

    MERGED_RAW.parent.mkdir(parents=True, exist_ok=True)
    df_merged.to_csv(MERGED_RAW, index=False)

    print(f"\n✅ Merge terminé :")
    print(f"   Adresses enrichies depuis med.ma : {enriched}")
    print(f"   Nouveaux médecins med.ma ajoutés : {new_count}")
    print(f"   Total merged_raw.csv             : {len(df_merged)} médecins")
    print(f"   → {MERGED_RAW}")


if __name__ == "__main__":
    run()
