"""
scraper_medma.py — med.ma Doctor Scraper
=========================================
Scrape tous les médecins de med.ma par spécialité × ville × quartier.
Output : data/raw/medma_raw.csv
Progress : data/medma_scraping_progress.json

Usage:
  python scraper_medma.py                          # toutes spécialités + villes
  python scraper_medma.py --limit 50               # test rapide
  python scraper_medma.py --specialites cardiologue dentiste --cities casablanca
"""

import re
import time
import json
import logging
import argparse
import threading
import pandas as pd
from pathlib import Path
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# ── Config ────────────────────────────────────────────────────────────────────

BASE_URL       = "https://www.med.ma"
RAW_OUTPUT     = Path("data/raw/medma_raw.csv")
PROGRESS_FILE  = Path("data/medma_scraping_progress.json")
REQUEST_DELAY  = 0.8

ALL_SPECIALITIES = [
    "dentiste", "cardiologue", "dermatologue", "gynecologue-obstetricien",
    "generaliste", "pediatre", "ophtalmologue", "neurologue", "psychiatre",
    "radiologue", "rhumatologue", "urologue", "pneumologue", "nephrologue",
    "gastro-enterologue", "nutritionniste", "endocrinologue-diabetologue",
    "interniste", "chirurgien-orthopediste-traumatologue", "oto-rhino-laryngologiste",
]

ALL_CITIES = [
    "agadir", "al-hoceima", "beni-mellal", "casablanca", "el-jadida",
    "fes", "kenitra", "khouribga", "laayoune", "larache", "marrakech",
    "meknes", "mohammedia", "nador", "ouarzazate", "oujda", "rabat",
    "safi", "sale", "settat", "tanger", "temara", "tetouan", "tiznit",
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("medma")

_flush_lock = threading.Lock()

# ── Helpers ───────────────────────────────────────────────────────────────────

def clean(text):
    return re.sub(r"\s+", " ", str(text or "").strip())

def extract_id(url):
    m = re.search(r"-(\d+)$", url.rstrip("/"))
    return m.group(1) if m else None

def write_progress(current, total, doctors, done=False):
    PROGRESS_FILE.write_text(json.dumps({
        "current": current, "total": total,
        "doctors": doctors, "done": done
    }))

# ── Listing : collecter les URLs de profil ────────────────────────────────────

def collect_profile_urls(page, url: str) -> list[str]:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(2000)
    except Exception as e:
        log.warning(f"Erreur listing {url}: {e}")
        return []

    urls: set[str] = set()

    def harvest():
        hrefs = page.eval_on_selector_all(
            'a[href*="/dr-"]',
            "els => els.map(e => e.getAttribute('href'))"
        )
        for h in hrefs:
            if h and "/medecin/" in h:
                urls.add(h if h.startswith("http") else BASE_URL + h)

    harvest()

    for _ in range(50):
        try:
            btn = page.locator("button:has-text('Voir'), a:has-text('Voir')").filter(
                has_text=re.compile(r"voir.{0,5}plus", re.I)
            ).first
            if not btn.is_visible(timeout=1500):
                break
            before = len(urls)
            btn.scroll_into_view_if_needed()
            btn.click()
            page.wait_for_timeout(int(REQUEST_DELAY * 1000))
            harvest()
            if len(urls) == before:
                break
        except Exception:
            break

    return list(urls)

# ── Profil : extraire les données ─────────────────────────────────────────────

def parse_profile(page, url: str) -> dict | None:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=25_000)
        page.wait_for_timeout(800)
    except Exception as e:
        log.warning(f"Erreur profil {url}: {e}")
        return None

    soup = BeautifulSoup(page.content(), "lxml")

    data = {
        "nom_professionnel": "",
        "profile_url":       url,
        "specialite":        "",
        "ville":             "",
        "adresse_complete":  "",
        "source":            "med.ma",
    }

    # Nom
    h1 = soup.find("h1")
    if h1:
        data["nom_professionnel"] = clean(h1.get_text()).title()

    # Spécialité + ville depuis breadcrumb ou URL
    for bc in soup.select("a[href*='/medecin/']"):
        href = bc.get("href", "").split("?")[0].rstrip("/")
        text = clean(bc.get_text())
        if not text:
            continue
        parts = href.split("/")
        # /medecin/spec → 3 parts after split, /medecin/spec/ville → 4 parts
        if len(parts) == 3 and not data["specialite"]:
            data["specialite"] = text
        elif len(parts) == 4 and not data["ville"]:
            data["ville"] = text

    # Fallback: extraire ville depuis l'URL directement
    if not data["ville"]:
        m = re.search(r"/medecin/[^/]+/([^/]+)/", url)
        if m:
            data["ville"] = m.group(1).replace("-", " ").title()

    # Adresse depuis span.profile__adr
    parts = []
    for span in soup.select("span.profile__adr"):
        t = re.sub(r"\d{5}\s*", "", span.get_text(separator=" ", strip=True))
        t = re.sub(r"\bMaroc\b", "", t, flags=re.I).strip(" ,")
        if t:
            parts.append(t)
    data["adresse_complete"] = ", ".join(parts)

    return data

# ── Scraper principal ─────────────────────────────────────────────────────────

# ── Scraper principal ─────────────────────────────────────────────────────────

def _listing_worker(combos: list[tuple]) -> list[str]:
    """Run in a thread — own Playwright browser for listing only."""
    urls = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR", viewport={"width": 1280, "height": 900}
        )
        ctx.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf,mp4}", lambda r: r.abort())
        page = ctx.new_page()
        for url in combos:
            urls.extend(collect_profile_urls(page, url))
        browser.close()
    return urls


def _profile_worker(urls: list[str]) -> list[dict]:
    """Run in a thread — own Playwright browser for profile scraping."""
    records = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR", viewport={"width": 1280, "height": 900}
        )
        ctx.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf,mp4}", lambda r: r.abort())
        page = ctx.new_page()
        for url in urls:
            record = parse_profile(page, url)
            if record:
                if not record["specialite"]:
                    m = re.search(r"/medecin/([^/]+)/", url)
                    if m:
                        record["specialite"] = m.group(1).replace("-", " ").title()
                records.append(record)
            time.sleep(REQUEST_DELAY)
        browser.close()
    return records


def run(specialities, cities, output=RAW_OUTPUT, resume=True, limit=None, workers=3):
    output.parent.mkdir(parents=True, exist_ok=True)

    existing_ids: set[str] = set()
    if resume and output.exists():
        try:
            df_ex = pd.read_csv(output, dtype=str)
            existing_ids = set(df_ex["profile_url"].apply(extract_id).dropna().tolist())
            log.info(f"Resume: {len(existing_ids)} médecins déjà scrapés")
        except Exception:
            pass

    # ── Phase 1 : Listing parallel ───────────────────────────────────────
    combos = []
    for spec in specialities:
        for city in (cities or [None]):
            url = f"{BASE_URL}/medecin/{spec}/{city}" if city else f"{BASE_URL}/medecin/{spec}"
            combos.append(url)

    log.info(f"Listing {len(combos)} combos avec {workers} browsers parallèles…")
    write_progress(0, len(combos), len(existing_ids))

    # Split combos across workers
    chunk = max(1, len(combos) // workers)
    chunks = [combos[i:i+chunk] for i in range(0, len(combos), chunk)]

    from concurrent.futures import ThreadPoolExecutor, as_completed
    all_urls_raw = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for result in ex.map(_listing_worker, chunks):
            all_urls_raw.extend(result)

    # Deduplicate + filter already scraped
    seen = set()
    all_urls = []
    for u in all_urls_raw:
        doc_id = extract_id(u)
        if u not in seen and not (resume and doc_id and doc_id in existing_ids):
            seen.add(u)
            all_urls.append(u)

    if limit:
        all_urls = all_urls[:limit]

    log.info(f"{len(all_urls)} profils à scraper")
    write_progress(0, len(all_urls), len(existing_ids))

    # ── Phase 2 : Profile scraping parallel ──────────────────────────────
    chunk2 = max(1, len(all_urls) // workers)
    url_chunks = [all_urls[i:i+chunk2] for i in range(0, len(all_urls), chunk2)]

    total = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_profile_worker, chunk): chunk for chunk in url_chunks}
        for fut in as_completed(futures):
            records = fut.result()
            if records:
                _flush(records, output, append=(output.exists()))
                total += len(records)
                write_progress(total, len(all_urls), len(existing_ids) + total)
                log.info(f"  {total}/{len(all_urls)} médecins scrapés")

    write_progress(len(all_urls), len(all_urls), len(existing_ids) + total, done=True)
    log.info(f"✅ {total} médecins scrapés → {output}")


def _flush(records, path, append):
    with _flush_lock:
        df = pd.DataFrame(records)
        mode = "a" if append else "w"
        header = not (append and path.exists() and path.stat().st_size > 0)
        df.to_csv(path, mode=mode, header=header, index=False, encoding="utf-8-sig")
    log.info(f"  💾 {len(records)} enregistrements sauvegardés")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scraper med.ma")
    parser.add_argument("--specialites", nargs="+", default=None)
    parser.add_argument("--all-specialites", action="store_true")
    parser.add_argument("--cities", nargs="+", default=None)
    parser.add_argument("--all-cities", action="store_true")
    parser.add_argument("--output", default=str(RAW_OUTPUT))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()

    run(
        specialities=ALL_SPECIALITIES if args.all_specialites else (args.specialites or ALL_SPECIALITIES),
        cities=ALL_CITIES if args.all_cities else args.cities,
        output=Path(args.output),
        resume=not args.no_resume,
        limit=args.limit,
        workers=args.workers,
    )
