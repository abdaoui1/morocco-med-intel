"""
enrich_from_medma.py
====================
Enrichit les adresses manquantes de dabadoc_raw.csv via med.ma.

Stratégie :
  1. Regroupe les médecins DabaDoc sans adresse par (ville, spécialité)
  2. Scrape med.ma listing → extrait nom + URL profil de chaque médecin
  3. Fuzzy match nom DabaDoc vs nom med.ma (threshold 85%)
  4. Si match → visite le profil pour récupérer span.profile__adr
  5. Met à jour dabadoc_raw.csv

Usage :
  python enrich_from_medma.py
  python enrich_from_medma.py --threshold 80 --limit 500
"""

import re
import time
import logging
import argparse
import csv
import unicodedata
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from rapidfuzz import fuzz

# ── Config ────────────────────────────────────────────────────────────────────

RAW_CSV         = Path("data/raw/dabadoc_raw.csv")
BASE_URL        = "https://www.med.ma"
MATCH_THRESHOLD = 85
REQUEST_DELAY   = 1.0
MAX_VOIR_PLUS   = 30

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("enrich")

# ── Mappings spécialité/ville → slug med.ma ───────────────────────────────────

SPEC_TO_SLUG = {
    "Dentiste":               "dentiste",
    "Dermatologue":           "dermatologue",
    "Gynécologue":            "gynecologue-obstetricien",
    "Cardiologue":            "cardiologue",
    "Pédiatre":               "pediatre",
    "Ophtalmologue":          "ophtalmologue",
    "Généraliste":            "generaliste",
    "Psychiatre/Psychologue": "psychiatre",
    "Radiologue":             "radiologue",
    "Chirurgien":             "chirurgien-orthopediste-traumatologue",
    "Pneumologue":            "pneumologue",
    "Gastro-entérologue":     "gastro-enterologue",
    "Neurologue":             "neurologue",
    "Cardiologue":            "cardiologue",
}

CITY_TO_SLUG = {
    "Casablanca": "casablanca", "Rabat": "rabat", "Marrakech": "marrakech",
    "Fès": "fes", "Agadir": "agadir", "Tanger": "tanger", "Meknès": "meknes",
    "Oujda": "oujda", "Kénitra": "kenitra", "Salé": "sale", "Témara": "temara",
    "Mohammedia": "mohammedia", "Béni Mellal": "beni-mellal", "Tétouan": "tetouan",
    "El Jadida": "el-jadida", "Safi": "safi", "Nador": "nador", "Inezgane": "agadir",
    "Laâyoune": "laayoune", "Tiznit": "tiznit", "Tanger": "tanger",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def normalize(text: str) -> str:
    text = "".join(
        c for c in unicodedata.normalize("NFD", str(text))
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", text.lower().strip())

def fuzzy_match(a: str, b: str) -> int:
    return fuzz.token_sort_ratio(normalize(a), normalize(b))

# ── Scraping ──────────────────────────────────────────────────────────────────

def scrape_listing(page, spec_slug: str, city_slug: str) -> list[dict]:
    """
    Retourne [{nom, profile_url}] depuis la page listing med.ma.
    Le nom et le quartier sont directement dans le texte du lien — pas besoin de visiter le profil.
    """
    url = f"{BASE_URL}/medecin/{spec_slug}/{city_slug}"
    log.info(f"  Listing: {url}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(2500)
    except Exception as e:
        log.warning(f"  Erreur: {e}")
        return []

    def harvest():
        return page.evaluate("""
            () => [...document.querySelectorAll('a[href*="/dr-"]')]
                  .map(e => ({
                      nom: e.innerText.trim().split('\\n')[0].trim(),
                      href: e.href
                  }))
                  .filter(l => l.href.includes('/medecin/') && l.nom.length > 3)
        """)

    results = harvest()

    # Cliquer "Voir plus" pour charger tous les résultats
    for _ in range(MAX_VOIR_PLUS):
        try:
            btn = page.locator("a, button").filter(
                has_text=re.compile(r"voir.{0,5}plus", re.I)
            ).first
            if not btn.is_visible(timeout=1500):
                break
            before = len(results)
            btn.scroll_into_view_if_needed()
            btn.click()
            page.wait_for_timeout(int(REQUEST_DELAY * 1000))
            results = harvest()
            if len(results) == before:
                break
        except Exception:
            break

    # Dédupliquer
    seen, unique = set(), []
    for r in results:
        if r["href"] not in seen:
            seen.add(r["href"])
            unique.append(r)

    log.info(f"    → {len(unique)} médecins")
    return unique


def get_address_from_profile(page, profile_url: str) -> str:
    """Visite la page de profil et retourne l'adresse depuis span.profile__adr."""
    try:
        page.goto(profile_url, wait_until="domcontentloaded", timeout=25_000)
        page.wait_for_timeout(1500)
    except Exception:
        return ""

    html = page.content()
    soup = BeautifulSoup(html, "lxml")

    parts = []
    for span in soup.select("span.profile__adr"):
        t = span.get_text(separator=" ", strip=True)
        # Enlever "Maroc" en fin + code postal
        t = re.sub(r"\d{5}\s*", "", t)
        t = re.sub(r"\bMaroc\b", "", t, flags=re.I).strip(" ,")
        if t:
            parts.append(t)

    return ", ".join(parts) if parts else ""

# ── Enrichissement principal ──────────────────────────────────────────────────

def enrich(threshold: int = MATCH_THRESHOLD, limit: int = None):
    if not RAW_CSV.exists():
        log.error(f"Fichier introuvable: {RAW_CSV}")
        return

    with open(RAW_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    fieldnames = list(rows[0].keys())

    # Médecins sans adresse
    missing = [
        r for r in rows
        if not r.get("adresse_complete", "").strip()
        or r["adresse_complete"].strip() in ("Non spécifiée", r.get("ville", ""))
    ]
    log.info(f"{len(missing)} médecins sans adresse / {len(rows)} total")
    if limit:
        missing = missing[:limit]

    # Familles de spécialités
    SPEC_FAMILIES = {
        "Dentiste":               ["dentiste"],
        "Dermatologue":           ["dermato"],
        "Gynécologue":            ["gynéco", "gynecologue"],
        "Cardiologue":            ["cardio"],
        "Pédiatre":               ["pédia", "pediatre"],
        "Ophtalmologue":          ["ophtalmo"],
        "Psychiatre/Psychologue": ["psych"],
        "Radiologue":             ["radio"],
        "Chirurgien":             ["chirur"],
        "Pneumologue":            ["pneumo"],
        "Gastro-entérologue":     ["gastro"],
        "Neurologue":             ["neurolo"],
        "Généraliste":            ["général", "generaliste"],
    }

    def get_spec_family(spec: str) -> str:
        s = normalize(spec.split(",")[0])
        for family, kws in SPEC_FAMILIES.items():
            if any(kw in s for kw in kws):
                return family
        return "Généraliste"

    # Grouper par (ville, spec_family)
    groups: dict[tuple, list] = {}
    for r in missing:
        key = (r.get("ville", ""), get_spec_family(r.get("specialite", "")))
        groups.setdefault(key, []).append(r)

    log.info(f"{len(groups)} groupes à scraper")

    enriched_map = {r["nom_professionnel"]: r for r in rows}
    enriched_count = 0
    processed = 0
    total_missing = len(missing)

    PROGRESS_FILE = Path("data/medma_progress.json")
    def write_progress(done=False):
        import json as _j
        PROGRESS_FILE.write_text(_j.dumps({
            "current": processed, "total": total_missing,
            "enriched": enriched_count, "done": done
        }))
    write_progress()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
        )
        context.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf}", lambda r: r.abort())
        page = context.new_page()

        for (ville, spec_family), group_rows in groups.items():
            spec_slug = SPEC_TO_SLUG.get(spec_family)
            city_slug = CITY_TO_SLUG.get(ville)
            if not spec_slug or not city_slug:
                log.debug(f"  Skip ({ville}, {spec_family}) — pas de slug")
                continue

            medma_list = scrape_listing(page, spec_slug, city_slug)
            if not medma_list:
                continue

            for row in group_rows:
                nom_daba = row.get("nom_professionnel", "")
                best_score, best_candidate = 0, None

                for candidate in medma_list:
                    score = fuzzy_match(nom_daba, candidate["nom"])
                    if score > best_score:
                        best_score = score
                        best_candidate = candidate

                if best_score >= threshold and best_candidate:
                    addr = get_address_from_profile(page, best_candidate["href"])
                    if addr:
                        log.info(f"  ✅ {best_score}% | {nom_daba!r} → {best_candidate['nom']!r} | {addr}")
                        enriched_map[nom_daba]["adresse_complete"] = addr
                        enriched_count += 1
                    else:
                        log.debug(f"  ⚠ Match ({best_score}%) mais adresse vide: {best_candidate['href']}")
                else:
                    log.debug(f"  ✗ {best_score}% | {nom_daba!r}")

                processed += 1
                if processed % 5 == 0:
                    write_progress()
                time.sleep(0.5)

        browser.close()

    write_progress(done=True)

    # Réécrire le CSV
    with open(RAW_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in enriched_map.values():
            writer.writerow({k: row.get(k, "") for k in fieldnames})

    log.info(f"\n✅ Terminé — {enriched_count} adresses ajoutées sur {len(missing)} traités")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=int, default=MATCH_THRESHOLD)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    enrich(threshold=args.threshold, limit=args.limit)
