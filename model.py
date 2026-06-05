#!/usr/bin/env python3
"""
Zone Saturation Prediction Model
=================================
Predicts whether a (ville, specialite, quartier) zone is saturated
based on doctor density and competition signals.

Target:  saturation = 1 if nb_doctors_in_zone >= median, else 0
Output:  models/saturation_model.pkl
         models/saturation_report.json
"""

import json
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, roc_auc_score
from sklearn.model_selection import train_test_split

MODELING_PATH = Path("data/processed/dabadoc_modeling.csv")
ANALYTICS_PATH = Path("data/processed/dabadoc_analytics.csv")
MODELS_DIR    = Path("models")
MODEL_PATH    = MODELS_DIR / "saturation_model.pkl"
REPORT_PATH   = MODELS_DIR / "saturation_report.json"

FEATURES = [
    "city_code", "spec_code", "district_code",
    "consultation_cabinet", "consultation_video", "consultation_domicile",
    "nb_avis_scaled", "latitude_scaled", "longitude_scaled",
]


def build_dataset() -> pd.DataFrame:
    """
    Build supervised dataset:
    Count doctors per (ville, specialite_clean, quartier_clean) → zone_count
    Label: saturated = 1 if zone_count >= median, else 0
    """
    df = pd.read_csv(MODELING_PATH)

    # Count doctors per zone
    zone_counts = (
        pd.read_csv(ANALYTICS_PATH)
        .groupby(["ville", "specialite_clean", "quartier_clean"])
        .size()
        .reset_index(name="zone_count")
    )

    df = df.merge(zone_counts, on=["ville", "specialite_clean", "quartier_clean"], how="left")
    df["zone_count"] = df["zone_count"].fillna(1)

    # Label: saturated if zone_count >= median
    median_count = df["zone_count"].median()
    df["saturated"] = (df["zone_count"] >= median_count).astype(int)

    print(f"📊 Dataset: {len(df)} samples | Saturated: {df['saturated'].mean():.1%}")
    return df


def train():
    print("🤖 Training Saturation Prediction Model…")
    MODELS_DIR.mkdir(exist_ok=True)

    df = build_dataset()

    # Drop rows with any NaN in features
    available = [f for f in FEATURES if f in df.columns]
    df = df.dropna(subset=available)

    X = df[available]
    y = df["saturated"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    model = RandomForestClassifier(n_estimators=100, random_state=42, class_weight="balanced")
    model.fit(X_train, y_train)

    # Evaluation
    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)[:, 1]
    report = classification_report(y_test, y_pred, output_dict=True)

    try:
        auc = roc_auc_score(y_test, y_prob)
    except Exception:
        auc = None

    # Feature importance
    importance = dict(zip(available, model.feature_importances_.tolist()))
    importance_sorted = dict(sorted(importance.items(), key=lambda x: x[1], reverse=True))

    print("\n📈 Feature Importance:")
    for feat, imp in importance_sorted.items():
        bar = "█" * int(imp * 40)
        print(f"  {feat:<25} {bar} {imp:.3f}")

    print(f"\n🎯 Accuracy:  {report['accuracy']:.3f}")
    print(f"🎯 AUC-ROC:   {auc:.3f}" if auc else "")
    print(f"🎯 F1 (macro): {report['macro avg']['f1-score']:.3f}")

    # Save model
    joblib.dump(model, MODEL_PATH)
    print(f"\n💾 Model saved → {MODEL_PATH}")

    # Save report
    result = {
        "accuracy":         round(report["accuracy"], 4),
        "auc_roc":          round(auc, 4) if auc else None,
        "f1_macro":         round(report["macro avg"]["f1-score"], 4),
        "feature_importance": importance_sorted,
        "features_used":    available,
        "n_train":          len(X_train),
        "n_test":           len(X_test),
        "saturated_rate":   round(y.mean(), 4),
    }
    REPORT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"💾 Report saved → {REPORT_PATH}")
    return model, result


def predict_zone(ville: str, specialite: str, quartier: str) -> dict:
    """Predict saturation for a given zone using the saved model."""
    if not MODEL_PATH.exists():
        raise FileNotFoundError("Model not found. Run model.py first.")

    model  = joblib.load(MODEL_PATH)
    report = json.loads(REPORT_PATH.read_text())
    available = report["features_used"]

    df = pd.read_csv(MODELING_PATH)
    row = df[
        (df["ville"] == ville) &
        (df["specialite_clean"] == specialite) &
        (df["quartier_clean"] == quartier)
    ]
    if row.empty:
        row = df[(df["ville"] == ville) & (df["specialite_clean"] == specialite)]
    if row.empty:
        row = df[df["ville"] == ville]
    if row.empty:
        return {"error": "No data available for this combination"}

    X = row[available].mean().to_frame().T

    prob = model.predict_proba(X)[0][1]
    label = "🔴 Saturé" if prob >= 0.5 else "🟢 Opportunité"

    return {
        "ville":            ville,
        "specialite":       specialite,
        "quartier":         quartier,
        "saturation_score": round(float(prob), 3),
        "label":            label,
    }


if __name__ == "__main__":
    train()
