#!/usr/bin/env python3
"""
DabaDoc - Data Cleaning & Processing Pipeline
==============================================
Input:  data/raw/dabadoc_raw.csv
Output: data/processed/dabadoc_clean.csv
        data/processed/dabadoc_analytics.csv
        data/processed/dabadoc_modeling.csv
"""

import hashlib
import re
import subprocess
import unicodedata
from pathlib import Path

import joblib
import pandas as pd
from sklearn.preprocessing import StandardScaler

_MERGED_PATH   = Path("data/raw/merged_raw.csv")
_DABADOC_PATH  = Path("data/raw/dabadoc_raw.csv")
RAW_PATH       = _MERGED_PATH if _MERGED_PATH.exists() else _DABADOC_PATH
CLEAN_PATH     = Path("data/processed/dabadoc_clean.csv")
ANALYTICS_PATH = Path("data/processed/dabadoc_analytics.csv")
MODELING_PATH  = Path("data/processed/dabadoc_modeling.csv")

DQV_MISSING_THRESHOLD = 0.15   # <15% missing per feature


# ── Helpers ────────────────────────────────────────────────────────────────

def anonymize_name(name: str) -> str:
    return hashlib.sha256(str(name).encode()).hexdigest()[:16]


def normalize_text(text: str) -> str:
    text = "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )
    return text.lower().strip()


def standardize_city(city) -> str:
    if not isinstance(city, str):
        return "Non spécifiée"
    city = city.strip().title()
    CORRECTIONS = {
        "Inzegane": "Inezgane", "Sale": "Salé", "Fes": "Fès",
        "Meknes": "Meknès", "Kenitra": "Kénitra", "Temara": "Témara",
        "Tetouan": "Tétouan", "Ben Mellal": "Béni Mellal",
        "Beni-Mellal": "Béni Mellal", "Mohammedia": "Mohammédia",
    }
    return CORRECTIONS.get(city, city)


def standardize_specialty(spec) -> str:
    if pd.isna(spec):
        return "Généraliste"
    s = spec.lower()
    FAMILIES = {
        "Dentiste":               ["dentiste", "orthodont", "implant", "buccale", "pédodont", "parodont", "endodont"],
        "Dermatologue":           ["dermato"],
        "Gynécologue":            ["gynéco"],
        "Psychiatre/Psychologue": ["psych"],
        "Pédiatre":               ["pédia"],
        "Cardiologue":            ["cardio"],
        "Ophtalmologue":          ["ophtalmo"],
        "Radiologue":             ["radio"],
        "Chirurgien":             ["chirur"],
        "Généraliste":            ["généraliste", "generaliste", "médecin généraliste"],
    }
    for family, keywords in FAMILIES.items():
        if any(kw in s for kw in keywords):
            return family
    return spec.split(",")[0].strip().capitalize()


_SPEC_PATTERN = re.compile(
    r",?\s*(gynécolog\w*|chirurgi\w*|cardiolog\w*|dermatolog\w*|pédiatr\w*|"
    r"ophtalmolog\w*|psychiatr\w*|neurologu\w*|radiolog\w*|urologu\w*|"
    r"généraliste\w*|dentiste\w*|orthopédi\w*|pneumolog\w*|rhumatolog\w*|"
    r"endocrinolog\w*|gastro[\w-]*|médecin\w*|stomatolog\w*|anesthési\w*|"
    r"oncolog\w*|nephrog\w*|infectiolog\w*)[\w\s,/-]*$",
    re.IGNORECASE,
)


def clean_address(addr, city) -> str:
    if not isinstance(addr, str) or not addr.strip():
        return "Non spécifiée"
    addr = re.sub(r"\bmaroc\b", "", addr, flags=re.IGNORECASE)
    if isinstance(city, str) and city.lower() not in ("non spécifiée", ""):
        addr = re.sub(re.escape(city), "", addr, flags=re.IGNORECASE)
    # Strip specialty names that bleed into address (scraper artefact)
    addr = _SPEC_PATTERN.sub("", addr)
    addr = re.sub(r"[\s,.-]+$", "", addr).strip()
    addr = re.sub(r",\s*\d{5}\s*$", "", addr).strip()
    # Remove double commas left behind
    addr = re.sub(r",\s*,", ",", addr).strip(" ,")
    return addr or "Non spécifiée"


def extract_quartier(addr) -> str:
    if not isinstance(addr, str) or addr == "Non spécifiée":
        return "Autre/Inconnu"

    # 1. Explicit "Quartier X" pattern
    m = re.search(r"\bq(?:uartier)?\.?\s+([A-ZÀ-Ÿa-zà-ÿ][A-ZÀ-Ÿa-zà-ÿ\s\-]{2,20})", addr, re.IGNORECASE)
    if m:
        return m.group(1).strip().title()

    clean = normalize_text(addr)

    # 2. Known districts (fast lookup for common ones)
    DISTRICTS = {
        "Maarif":           ["maarif"],
        "Gauthier":         ["gauthier"],
        "Agdal":            ["agdal"],
        "2 Mars":           ["2 mars", "2mars"],
        "Hay Riad":         ["hay riad", "hay ryad"],
        "California":       ["california"],
        "Bourgogne":        ["bourgogne", "bourgognes"],
        "Centre Ville":     ["centre ville", "centre-ville"],
        "Hay Hassani":      ["hay hassani", "hay el hassani", "hay elhassani"],
        "Oasis":            ["oasis"],
        "Palmier":          ["palmier"],
        "Inezgane":         ["inezgane", "inzegane"],
        "Sidi Maarouf":     ["sidi maarouf"],
        "Ain Sebaa":        ["ain sebaa"],
        "Atlas":            ["atlas"],
        "Akkari":           ["akkari"],
        "Hay Nahda":        ["hay nahda", "nahda"],
        "Diour Jamaa":      ["diour jamaa"],
        "Les Hôpitaux":     ["hopitaux", "hôpitaux", "les hopitaux", "des hopitaux"],
        "Massira":          ["massira"],
        "Hay Inara":        ["inara"],
        "Guéliz":           ["gueliz", "guéliz"],
        "Hivernage":        ["hivernage"],
        "Mellah":           ["mellah"],
        "Anfa":             ["anfa"],
        "Racine":           ["racine"],
        "Route El Jadida":  ["route el jadida"],
        "Hay Mohammadi":    ["hay mohammadi", "hay mohamadi", "hay mohammedia"],
        "Derb Sultan":      ["derb sultan"],
        "Al Qods":          ["al qods", "al quods", "el qods", "el quods", "hay al qods", "hay qods"],
        "Hay Oulfa":        ["hay oulfa", "hay el oulfa", "hay eloulfa", "el oulfa"],
        "Sbata":            ["sbata"],
        "Ain Chock":        ["ain chock", "ain chok"],
        "Bernoussi":        ["bernoussi"],
        "Hay Salama":       ["hay salama", "hay essalama"],
        "Sidi Bernoussi":   ["sidi bernoussi"],
        "Abdelmoumen":      ["abdelmoumen"],
        "Belvédère":        ["belveder", "belvedere", "belvédère"],
        "Mers Sultan":      ["mers sultan"],
        "El Fida":          ["el fida"],
    }
    for canon, patterns in DISTRICTS.items():
        if any(p in clean for p in patterns):
            return canon

    # 3. Dynamic extraction — Hay/Cite/Sidi/Lotissement only (real neighbourhood prefixes)
    m2 = re.search(
        r"\b(hay|cité|cite|sidi|lotissement)\s+([A-ZÀ-Ÿa-zà-ÿ][A-ZÀ-Ÿa-zà-ÿ\s]{2,20}?)(?:\s*[,/\d]|$)",
        addr, re.IGNORECASE
    )
    if m2:
        return (m2.group(1) + " " + m2.group(2)).strip().title()

    # 4. No reliable match → Autre/Inconnu (don't invent quartiers from street names)
    return "Autre/Inconnu"


# ── DQV Gate ───────────────────────────────────────────────────────────────

def run_dqv(df: pd.DataFrame) -> bool:
    """
    Data Quality Verification Gate.
    Returns True if all checks pass, False otherwise (pipeline stops).
    """
    print("\n🔍 [DQV] Running Data Quality Checks…")
    passed = True

    # 1. Missing Value Check (<15% per feature)
    # Optional fields (deep-scrape only) are allowed up to 100% missing
    OPTIONAL_COLS = {"latitude", "longitude", "adresse_complete"}
    print("  [1/5] Missing Value Check…")
    for col in df.columns:
        missing_rate = df[col].isna().mean()
        if col in OPTIONAL_COLS:
            print(f"  ⚠️  '{col}': {missing_rate:.1%} missing (optional)")
            continue
        if missing_rate > DQV_MISSING_THRESHOLD:
            print(f"  ❌ FAIL — '{col}': {missing_rate:.1%} missing (threshold: {DQV_MISSING_THRESHOLD:.0%})")
            passed = False
        else:
            print(f"  ✅ '{col}': {missing_rate:.1%} missing")

    # 2. Duplicate Check
    print("  [2/5] Duplicate Check…")
    dupes = df.duplicated(subset=["nom_professionnel", "ville"]).sum()
    if dupes > 0:
        print(f"  ⚠️  WARNING — {dupes} duplicate (nom+ville) found (will be removed)")
    else:
        print(f"  ✅ No duplicates found")

    # 3. Domain / Type Validity Check
    print("  [3/5] Domain & Type Validity Check…")
    if "latitude" in df.columns:
        df_gps = df.dropna(subset=["latitude", "longitude"])
        invalid_lat = ((df_gps["latitude"] < 27) | (df_gps["latitude"] > 36)).sum()
        invalid_lon = ((df_gps["longitude"] < -14) | (df_gps["longitude"] > -1)).sum()
        if invalid_lat + invalid_lon > 0:
            print(f"  ⚠️  WARNING — GPS: {invalid_lat} invalid latitudes, {invalid_lon} invalid longitudes (will be nullified)")
        else:
            print(f"  ✅ GPS: all coordinates within Morocco bounds")
    if "specialite" in df.columns:
        empty_spec = (df["specialite"].str.strip() == "").sum()
        if empty_spec > 0:
            print(f"  ⚠️  WARNING — {empty_spec} empty specialite values (will default to Généraliste)")
        else:
            print(f"  ✅ specialite: no empty values")

    # 4. Distribution Consistency Check
    print("  [4/5] Distribution Check…")
    if "specialite_clean" in df.columns:
        top_spec = df["specialite_clean"].value_counts()
        dominant_pct = top_spec.iloc[0] / len(df)
        if dominant_pct > 0.80:
            print(f"  ⚠️  WARNING — Distribution skewed: '{top_spec.index[0]}' = {dominant_pct:.1%} of data")
        else:
            print(f"  ✅ Distribution OK — top specialty: {dominant_pct:.1%}")
    if "ville" in df.columns:
        top_ville_pct = df["ville"].value_counts().iloc[0] / len(df)
        if top_ville_pct > 0.90:
            print(f"  ⚠️  WARNING — Geo distribution skewed: {top_ville_pct:.1%} from one city")
        else:
            print(f"  ✅ Geo distribution OK")

    # 5. Cross-feature Consistency Check
    print("  [5/5] Cross-feature Consistency Check…")
    if "nom_professionnel" in df.columns and "doctor_id" in df.columns:
        id_conflicts = df.groupby("doctor_id")["nom_professionnel"].nunique()
        conflicts = (id_conflicts > 1).sum()
        if conflicts > 0:
            print(f"  ❌ FAIL — {conflicts} doctor_id hash collisions detected")
            passed = False
        else:
            print(f"  ✅ doctor_id: no hash collisions")

    status = "✅ [DQV GATE OPENED]" if passed else "❌ [DQV GATE CLOSED — Fix issues above]"
    print(f"\n  {status}\n")
    return passed


# ── DVC versioning ─────────────────────────────────────────────────────────

def dvc_commit_and_tag(version: str = "v1.0-anonymized"):
    """Add processed files to DVC tracking and create a git tag."""
    print(f"📦 [DVC] Committing and tagging version {version}…")
    try:
        # dvc add the processed outputs
        for path in [CLEAN_PATH, ANALYTICS_PATH, MODELING_PATH]:
            subprocess.run(["dvc", "add", str(path)], check=True, capture_output=True)

        # git add dvc files + git commit
        subprocess.run(["git", "add", "--all"], check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", f"chore: DVC clean data {version}"],
            check=True, capture_output=True
        )

        # git tag
        subprocess.run(
            ["git", "tag", "-f", version, "-m", f"Clean dataset {version}"],
            check=True, capture_output=True
        )
        print(f"  ✅ DVC commit + tag '{version}' created")
    except subprocess.CalledProcessError as e:
        print(f"  ⚠️  DVC/Git step skipped: {e.stderr.decode(errors='ignore').strip() or str(e)}")
    except FileNotFoundError:
        print("  ⚠️  DVC or Git not found in PATH — skipping versioning step")


# ── Pipeline ───────────────────────────────────────────────────────────────

def run():
    print("📋 Starting DabaDoc Cleaning Pipeline…")

    raw_path = _MERGED_PATH if _MERGED_PATH.exists() else _DABADOC_PATH
    if not raw_path.exists():
        print(f"❌ Raw file not found. Expected: {_MERGED_PATH} or {_DABADOC_PATH}")
        return
    if raw_path == _DABADOC_PATH:
        print(f"⚠️  merged_raw.csv not found — falling back to {_DABADOC_PATH}")

    df = pd.read_csv(raw_path)
    print(f"📥 Loaded {len(df)} records from {raw_path}")

    # ── 1. Basic cleaning
    df["nom_professionnel"] = df["nom_professionnel"].str.strip().str.title()
    df["ville"]             = df["ville"].apply(standardize_city)
    df["specialite"]        = df["specialite"].fillna("Généraliste").str.strip()

    # ── 2. Address cleaning
    df["adresse_complete"] = df.apply(
        lambda r: clean_address(r.get("adresse_complete", ""), r["ville"]), axis=1
    )

    # ── 3. Derived columns
    df["quartier_clean"]   = df["adresse_complete"].apply(extract_quartier)
    df["specialite_clean"] = df["specialite"].apply(standardize_specialty)
    df["doctor_id"]        = df["nom_professionnel"].apply(anonymize_name)
    if "source" not in df.columns:
        df["source"] = "DabaDoc"

    # ── 4. Deduplication
    df["dedup_key"] = (
        df["nom_professionnel"].apply(lambda n: re.sub(r"\s+", "", normalize_text(str(n))))
        + "_" + df["ville"].str.upper()
    )
    df = df.drop_duplicates(subset=["dedup_key"], keep="first").copy()
    df = df.drop(columns=["dedup_key"])
    print(f"✅ After deduplication: {len(df)} doctors")

    # ── 5. Ensure numeric types for GPS + nullify out-of-bounds coordinates
    for col in ["latitude", "longitude"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "latitude" in df.columns:
        mask = (df["latitude"] < 27) | (df["latitude"] > 36) | (df["longitude"] < -14) | (df["longitude"] > -1)
        invalid = mask.sum()
        if invalid:
            print(f"  ⚠️  Nullified {invalid} GPS coordinates outside Morocco bounds")
            df.loc[mask, ["latitude", "longitude"]] = None

    # ── 6. DQV Gate ── STOP pipeline if critical checks fail
    dqv_passed = run_dqv(df)
    if not dqv_passed:
        print("🛑 Pipeline stopped — fix DQV issues and re-run.")
        return

    # ── 7. Save clean
    CLEAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(CLEAN_PATH, index=False)
    print(f"💾 Clean data → {CLEAN_PATH} ({len(df)} rows)")

    # ── 8. Analytics (explode specialties)
    df_a = df.copy()
    df_a["specialite"] = df_a["specialite"].str.split(",")
    df_a = df_a.explode("specialite")
    df_a["specialite"] = df_a["specialite"].str.strip().str.capitalize()
    df_a = df_a[df_a["specialite"].str.len() > 2]
    df_a.to_csv(ANALYTICS_PATH, index=False)
    print(f"💾 Analytics data → {ANALYTICS_PATH} ({len(df_a)} rows)")

    # ── 9. Modeling: encoded + StandardScaler on numeric features
    base_cols = ["doctor_id", "ville", "specialite_clean", "quartier_clean"]
    optional  = ["latitude", "longitude"]
    model_cols = base_cols + [c for c in optional if c in df.columns]
    df_m = df[model_cols].copy()

    df_m["city_code"]     = df_m["ville"].astype("category").cat.codes
    df_m["spec_code"]     = df_m["specialite_clean"].astype("category").cat.codes
    df_m["district_code"] = df_m["quartier_clean"].astype("category").cat.codes

    # StandardScaler on continuous numeric columns
    scale_cols = [c for c in ["latitude", "longitude"] if c in df_m.columns]
    if scale_cols:
        df_m[scale_cols] = df_m[scale_cols].fillna(0)
        scaler = StandardScaler()
        df_m[[f"{c}_scaled" for c in scale_cols]] = scaler.fit_transform(df_m[scale_cols])
        df_m = df_m.drop(columns=scale_cols)  # keep only scaled versions
        Path("models").mkdir(exist_ok=True)
        joblib.dump(scaler, "models/scaler.pkl")
        print(f"  ✅ StandardScaler applied on: {scale_cols}")

    df_m.to_csv(MODELING_PATH, index=False)
    print(f"💾 Modeling data → {MODELING_PATH} ({len(df_m)} rows)")

    # ── 10. DVC commit + tag
    dvc_commit_and_tag("v1.0-anonymized")

    print("\n🏁 Pipeline complete.")


if __name__ == "__main__":
    run()
