#!/usr/bin/env python3
"""
DabaDoc.com - Medical Doctors Scraper for Morocco
==================================================
Output columns: nom_professionnel, profile_url, specialite, ville, adresse_complete,
                latitude, longitude, nb_avis, consultation_cabinet, consultation_video,
                consultation_domicile
"""

import argparse
import csv
import logging
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL   = "https://www.dabadoc.com"
SEARCH_URL = (
    "https://www.dabadoc.com/recherche/page/{page}"
    "?button=&country=MA"
    "&search%5Bbooking_type%5D=0&search%5Bcity_id%5D="
    "&search%5Bdoctor_speciality_id%5D=&search%5Bquery%5D=&search%5Btype%5D=false"
)
HEADERS_POOL = [
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Referer": "https://www.dabadoc.com/ma",
    },
    {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-MA,fr;q=0.9",
        "Referer": "https://www.dabadoc.com/ma",
    }
]

FIELD_NAMES = [
    "nom_professionnel", "profile_url", "specialite", "ville",
    "adresse_complete", "latitude", "longitude",
    "nb_avis", "consultation_cabinet", "consultation_video", "consultation_domicile"
]

@dataclass
class Doctor:
    nom_professionnel:     Optional[str] = None
    profile_url:           Optional[str] = None
    specialite:            Optional[str] = None
    ville:                 Optional[str] = None
    adresse_complete:      Optional[str] = None
    latitude:              Optional[str] = None
    longitude:             Optional[str] = None
    nb_avis:               Optional[int] = None
    consultation_cabinet:  bool = False
    consultation_video:    bool = False
    consultation_domicile: bool = False


def make_session() -> requests.Session:
    s = requests.Session()
    h = random.choice(HEADERS_POOL).copy()
    try:
        s.get(f"{BASE_URL}/ma", headers=h, timeout=15)
        time.sleep(random.uniform(0.5, 1.2))
    except Exception:
        pass
    return s


def fetch(session: requests.Session, url: str, retries: int = 3) -> Optional[str]:
    h = random.choice(HEADERS_POOL).copy()
    for attempt in range(retries):
        try:
            r = session.get(url, headers=h, timeout=20, allow_redirects=True)
            if r.status_code == 200:
                return r.text
            if r.status_code == 429:
                wait = 30 * (attempt + 1)
                logging.warning(f"Rate-limited. Waiting {wait}s…")
                time.sleep(wait)
                continue
            if r.status_code in (403, 404):
                return None
        except requests.RequestException:
            pass
        time.sleep(5 * (attempt + 1))
    return None


def parse_search_page(html: str) -> list[Doctor]:
    soup = BeautifulSoup(html, "lxml")
    doctors = []

    for card in soup.select("div.result-box"):
        # Name
        name_tag = card.select_one("h2 a") or card.select_one("h3 a")
        name = name_tag.get_text(strip=True) if name_tag else None

        # Profile URL
        url_tag = card.select_one("a.profile_url") or card.select_one("h2 a") or card.select_one("a.btn-profile")
        prof_url = None
        if url_tag and url_tag.get("href"):
            href = url_tag["href"].split("?")[0]
            prof_url = href if href.startswith("http") else urljoin(BASE_URL, href)

        # Speciality + City from "Spec à Ville" paragraph
        specialite, ville = None, None
        for p in card.find_all("p"):
            text = re.sub(r"\s+", " ", p.get_text(separator=" ", strip=True))
            m = re.search(r"^(.+?)\s+à\s+(\S.+)$", text)
            if m:
                specialite = m.group(1).strip()
                ville = m.group(2).strip()
                break

        if name:
            doctors.append(Doctor(
                nom_professionnel=re.sub(r"\s+", " ", name).strip(),
                profile_url=prof_url,
                specialite=specialite,
                ville=ville,
            ))
    return doctors


def parse_profile_page(html: str, doc: Doctor) -> Doctor:
    soup = BeautifulSoup(html, "lxml")

    # Address — try multiple selectors to handle different profile layouts
    addr = None

    # Layout 1: address inside a <p> or <div> directly under the accès section
    info = soup.select_one(".info-section")
    if info:
        lines = [l.strip() for l in info.get_text(separator="\n", strip=True).split("\n") if l.strip()]
        for i, line in enumerate(lines):
            if "accès" in line.lower() and i + 1 < len(lines):
                addr = lines[i + 1]
                break

    # Layout 2: address next to a map-pin icon (fa-map-marker or similar)
    if not addr:
        pin = soup.select_one("i.fa-map-marker, i.fa-location-dot, span.address, .doctor-address")
        if pin:
            parent = pin.find_parent()
            if parent:
                addr = parent.get_text(separator=" ", strip=True)

    # Layout 3: paragraph inside .indications-section or .access-section
    if not addr:
        for sel in [".indications-section p", ".access-section p", ".cabinet-section p"]:
            tag = soup.select_one(sel)
            if tag:
                text = tag.get_text(separator=" ", strip=True)
                if len(text) > 8:
                    addr = text
                    break

    # Fallback: any line with a street/number pattern near "accès" anywhere in page
    if not addr:
        full_text = soup.get_text(separator="\n")
        lines = [l.strip() for l in full_text.split("\n") if l.strip()]
        for i, line in enumerate(lines):
            if "accès" in line.lower() or "adresse" in line.lower():
                for candidate in lines[i+1:i+4]:
                    if re.search(r"\d|rue|bd|avenue|quartier|boulevard", candidate, re.I) and len(candidate) > 8:
                        addr = candidate
                        break
            if addr:
                break

    doc.adresse_complete = addr

    # GPS from Google Maps link
    maps_link = soup.select_one("a[href*='google.com/maps?q=']")
    if maps_link:
        m = re.search(r"q=([-\d.]+),([-\d.]+)", maps_link["href"])
        if m:
            doc.latitude  = m.group(1)
            doc.longitude = m.group(2)

    # Number of avis
    reviews = soup.select(".review-holder")
    doc.nb_avis = len(reviews)

    # Consultation types
    consult_text = " ".join(
        t.get_text(strip=True).lower()
        for t in soup.select(".dl-text-body, .cabinet-section")
    )
    doc.consultation_cabinet  = "cabinet" in consult_text
    doc.consultation_video    = "vidéo" in consult_text or "video" in consult_text
    doc.consultation_domicile = "domicile" in consult_text

    return doc


def scrape(start: int, end: int, delay: tuple, workers: int, deep: bool, output: str, resume: bool):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)

    seen_names: set = set()
    if resume and out.exists():
        with open(out, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                seen_names.add(row.get("nom_professionnel", ""))
        logging.info(f"Resume: {len(seen_names)} doctors already scraped.")

    session = make_session()
    doctors: list[Doctor] = []
    progress_file = Path("data/scraping_progress.json")
    progress_file.parent.mkdir(parents=True, exist_ok=True)
    # Reset progress at start
    progress_file.write_text(
        f'{{"current": 0, "total": {end - start + 1}, "doctors": 0, "done": false}}'
    )
    total_pages = end - start + 1

    first_save = True  # track if we've written the header yet

    for i, page in enumerate(range(start, end + 1), 1):
        logging.info(f"Page {i}/{total_pages} (page {page})…")
        progress_file.write_text(
            f'{{"current": {i}, "total": {total_pages}, "doctors": {len(doctors) + len(seen_names)}, "done": false}}'
        )
        html = fetch(session, SEARCH_URL.format(page=page))
        if not html:
            continue
        for d in parse_search_page(html):
            if d.nom_professionnel and d.nom_professionnel not in seen_names:
                doctors.append(d)
                seen_names.add(d.nom_professionnel)
        time.sleep(random.uniform(*delay))
        # Incremental save every 50 pages
        if i % 50 == 0:
            session = make_session()
            if doctors:
                _mode = "w" if first_save and not (resume and out.exists()) else "a"
                with open(out, _mode, newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=FIELD_NAMES)
                    if _mode == "w":
                        writer.writeheader()
                    for d in doctors:
                        writer.writerow({
                            "nom_professionnel": d.nom_professionnel or "Inconnu",
                            "profile_url": d.profile_url or "",
                            "specialite": d.specialite or "Généraliste",
                            "ville": d.ville or "Non spécifiée",
                            "adresse_complete": d.adresse_complete or "",
                            "latitude": d.latitude or "",
                            "longitude": d.longitude or "",
                            "nb_avis": d.nb_avis if d.nb_avis is not None else "",
                            "consultation_cabinet": int(d.consultation_cabinet),
                            "consultation_video": int(d.consultation_video),
                            "consultation_domicile": int(d.consultation_domicile),
                        })
                logging.info(f"💾 Incremental save: {len(doctors)} new doctors written")
                first_save = False
                doctors = []  # clear buffer after save

    if deep:
        # Reload all newly scraped doctors from file for deep scraping
        all_new = []
        if out.exists():
            with open(out, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    if not row.get("adresse_complete", "").strip():
                        all_new.append(Doctor(
                            nom_professionnel=row["nom_professionnel"],
                            profile_url=row["profile_url"],
                            specialite=row["specialite"],
                            ville=row["ville"],
                        ))
        if all_new:
            logging.info(f"Deep scraping {len(all_new)} profile pages…")

            def _enrich(doc: Doctor) -> Doctor:
                if not doc.profile_url:
                    return doc
                s = make_session()  # thread-safe: one session per thread
                html = fetch(s, doc.profile_url)
                if html:
                    doc = parse_profile_page(html, doc)
                time.sleep(random.uniform(0.5, 1.5))
                return doc

            enriched: dict = {}
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futures = {ex.submit(_enrich, d): d for d in all_new}
                for fut in as_completed(futures):
                    d = fut.result()
                    enriched[d.nom_professionnel] = d

            # Update CSV with enriched data
            if out.exists():
                with open(out, newline="", encoding="utf-8") as f:
                    rows = list(csv.DictReader(f))
                with open(out, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=FIELD_NAMES)
                    writer.writeheader()
                    for row in rows:
                        d = enriched.get(row["nom_professionnel"])
                        if d:
                            row["adresse_complete"]     = d.adresse_complete or row["adresse_complete"]
                            row["latitude"]             = d.latitude or row["latitude"]
                            row["longitude"]            = d.longitude or row["longitude"]
                            row["nb_avis"]              = d.nb_avis if d.nb_avis is not None else row["nb_avis"]
                            row["consultation_cabinet"] = int(d.consultation_cabinet)
                            row["consultation_video"]   = int(d.consultation_video)
                            row["consultation_domicile"]= int(d.consultation_domicile)
                        writer.writerow(row)
            logging.info(f"✅ Deep scrape complete — {len(enriched)} profiles enriched")

    # Final save — remaining doctors not yet written (last batch < 50 pages)
    if doctors:
        _mode = "w" if first_save and not (resume and out.exists()) else "a"
        with open(out, _mode, newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELD_NAMES)
            if _mode == "w":
                writer.writeheader()
            for d in doctors:
                writer.writerow({
                    "nom_professionnel":     d.nom_professionnel or "Inconnu",
                    "profile_url":           d.profile_url or "",
                    "specialite":            d.specialite or "Généraliste",
                    "ville":                 d.ville or "Non spécifiée",
                    "adresse_complete":      d.adresse_complete or "",
                    "latitude":              d.latitude or "",
                    "longitude":             d.longitude or "",
                    "nb_avis":               d.nb_avis if d.nb_avis is not None else "",
                    "consultation_cabinet":  int(d.consultation_cabinet),
                    "consultation_video":    int(d.consultation_video),
                    "consultation_domicile": int(d.consultation_domicile),
                })
        logging.info(f"✅ Final save: {len(doctors)} doctors written")
    progress_file = Path("data/scraping_progress.json")
    total_saved = len(seen_names)
    progress_file.write_text(
        f'{{"current": {end - start + 1}, "total": {end - start + 1}, "doctors": {total_saved}, "done": true}}'
    )


def enrich_missing(output: str, workers: int, delay: tuple):
    """Visit profile pages for doctors that have no address in the raw CSV."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    out = Path(output)
    if not out.exists():
        logging.error(f"File not found: {out}")
        return

    df = []
    with open(out, newline="", encoding="utf-8") as f:
        df = list(csv.DictReader(f))

    missing = [r for r in df if not r.get("adresse_complete", "").strip()]
    logging.info(f"Found {len(missing)} doctors without address (out of {len(df)})")

    if not missing:
        logging.info("Nothing to enrich.")
        return

    progress_file = Path("data/scraping_progress.json")
    progress_file.write_text(
        f'{{"current": 0, "total": {len(missing)}, "doctors": {len(df)}, "done": false, "phase": "enrich", "enrich_total": {len(missing)}}}'
    )

    session = make_session()

    def _enrich_row(row: dict) -> dict:
        url = row.get("profile_url", "")
        if not url:
            return row
        s = make_session()  # thread-safe: one session per call
        html = fetch(s, url)
        if html:
            doc = Doctor(
                nom_professionnel=row["nom_professionnel"],
                profile_url=url,
                specialite=row.get("specialite"),
                ville=row.get("ville"),
            )
            doc = parse_profile_page(html, doc)
            if doc.adresse_complete:
                row["adresse_complete"] = doc.adresse_complete
            if doc.latitude:
                row["latitude"] = doc.latitude
                row["longitude"] = doc.longitude
            if doc.nb_avis:
                row["nb_avis"] = doc.nb_avis
            row["consultation_cabinet"]  = int(doc.consultation_cabinet)
            row["consultation_video"]    = int(doc.consultation_video)
            row["consultation_domicile"] = int(doc.consultation_domicile)
        time.sleep(random.uniform(*delay))
        return row

    enriched_map = {r["nom_professionnel"]: r for r in df}
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_enrich_row, r): r for r in missing}
        for fut in as_completed(futures):
            result = fut.result()
            enriched_map[result["nom_professionnel"]] = result
            done += 1
            if done % 10 == 0 or done == len(missing):
                progress_file.write_text(
                    f'{{"current": {done}, "total": {len(missing)}, "doctors": {len(df)}, "done": false, "phase": "enrich"}}'
                )
                logging.info(f"Enriched {done}/{len(missing)}")

    # Write back full CSV
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELD_NAMES)
        writer.writeheader()
        for row in enriched_map.values():
            writer.writerow({k: row.get(k, "") for k in FIELD_NAMES})

    logging.info(f"✅ Enrichment complete — {len(missing)} profiles updated")
    progress_file.write_text(
        f'{{"current": {len(missing)}, "total": {len(missing)}, "doctors": {len(df)}, "done": true, "phase": "enrich"}}'
    )


def main():
    p = argparse.ArgumentParser(description="DabaDoc Scraper")
    p.add_argument("--pages",       nargs=2, type=int,   default=[1, 1297])
    p.add_argument("--delay",       nargs=2, type=float, default=[1.5, 3.5])
    p.add_argument("--output",      default="data/raw/dabadoc_raw.csv")
    p.add_argument("--workers",     type=int, default=3)
    p.add_argument("--deep-scrape", action="store_true", help="Fetch profile pages (address, GPS, avis, consultation types)")
    p.add_argument("--resume",      action="store_true")
    p.add_argument("--enrich-missing", action="store_true", help="Enrich doctors without address in existing CSV")
    args = p.parse_args()
    if args.enrich_missing:
        enrich_missing(args.output, args.workers, tuple(args.delay))
    else:
        scrape(args.pages[0], args.pages[1], tuple(args.delay), args.workers, args.deep_scrape, args.output, args.resume)


if __name__ == "__main__":
    main()
