# 🩺 Morocco Medical Data Intelligence

Pipeline complet de **Data Engineering & ML** pour analyser la répartition des médecins au Maroc, basé sur les données de [DabaDoc.com](https://www.dabadoc.com).

## Architecture

```
DabaDoc.com
    ↓  scraper_dabadoc.py    (BeautifulSoup — collecte ~38k médecins)
data/raw/dabadoc_raw.csv
    ↓  clean_data.py         (Nettoyage + DQV Gate + DVC Versioning)
data/processed/
    ├── dabadoc_clean.csv    (données nettoyées + anonymisées)
    ├── dabadoc_analytics.csv
    └── dabadoc_modeling.csv (encodé + normalisé)
    ↓  model.py              (RandomForest — prédiction saturation)
models/saturation_model.pkl
    ↓  api.py                (FastAPI REST API)
    ↓  app.py                (Streamlit Dashboard)
```

## Données collectées (par médecin)

| Champ | Description |
|-------|-------------|
| `nom_professionnel` | Nom complet |
| `profile_url` | Lien DabaDoc |
| `specialite` | Spécialité(s) |
| `ville` | Ville |
| `adresse_complete` | Adresse complète |
| `latitude / longitude` | Coordonnées GPS |
| `nb_avis` | Nombre d'avis patients |
| `consultation_cabinet/video/domicile` | Types de consultation |

## Pipeline — Étapes

1. **Scraping** — BeautifulSoup sur DabaDoc (search + profil pages)
2. **Nettoyage** — standardisation villes, adresses, spécialités
3. **Anonymisation PHI** — SHA-256 hash → `doctor_id`
4. **DQV Gate** — 5 checks qualité (missing, duplicates, domain, distribution, cross-feature)
5. **Versioning** — DVC auto-commit + tag `v1.0-anonymized`
6. **Modeling** — encoding catégoriel + StandardScaler
7. **ML** — RandomForest pour prédiction de saturation de zone
8. **API** — FastAPI REST (6 endpoints documentés)
9. **Dashboard** — Streamlit (carte GPS, analyse, gaps, ML)

## Installation

```bash
pip install -r requirements.txt
```

## Utilisation

### 1. Scraper (10 pages test)
```bash
python scraper_dabadoc.py --pages 1 10 --deep-scrape
```

### 2. Nettoyage + DQV + DVC
```bash
python clean_data.py
```

### 3. Entraîner le modèle ML
```bash
python model.py
```

### 4. Lancer l'API
```bash
uvicorn api:app --reload --port 8000
# Swagger docs: http://localhost:8000/docs
```

### 5. Lancer le Dashboard
```bash
streamlit run app.py
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /stats` | KPIs globaux |
| `GET /medecins` | Liste paginée + filtres (ville, spécialité) |
| `GET /villes` | Médecins par ville |
| `GET /specialites` | Médecins par spécialité |
| `GET /carte` | Points GPS filtrables |
| `GET /gaps` | Quartiers sans concurrence |

## Modèle ML

- **Algorithme**: RandomForest Classifier
- **Target**: `saturated` (1 = zone saturée, 0 = opportunité)
- **Features**: spec_code, GPS, district_code, nb_avis, consultation types
- **Accuracy**: ~73% (sur 10 pages test — augmente avec plus de data)
