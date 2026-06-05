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

    # Address from info-section (line after "Indications / Détail Accès")
    info = soup.select_one(".info-section")
    if info:
        lines = [l.strip() for l in info.get_text(separator="\n", strip=True).split("\n") if l.strip()]
        for i, line in enumerate(lines):
            if "accès" in line.lower() and i + 1 < len(lines):
                doc.adresse_complete = lines[i + 1]
                break
        if not doc.adresse_complete and lines:
            # Fallback: first line that looks like an address (has a number or "Rue")
            for line in lines:
                if re.search(r"\d|rue|bd|avenue|quartier", line, re.I):
                    doc.adresse_complete = line
                    break

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
    total_pages = end - start + 1

    for i, page in enumerate(range(start, end + 1), 1):
        logging.info(f"Page {i}/{total_pages} (page {page})…")
        progress_file.write_text(
            f'{{"current": {i}, "total": {total_pages}, "doctors": {len(doctors)}, "done": false}}'
        )
        html = fetch(session, SEARCH_URL.format(page=page))
        if not html:
            continue
        for d in parse_search_page(html):
            if d.nom_professionnel and d.nom_professionnel not in seen_names:
                doctors.append(d)
        time.sleep(random.uniform(*delay))
        if page % 50 == 0:
            session = make_session()

    if deep and doctors:
        logging.info(f"Deep scraping {len(doctors)} profile pages…")

        def _enrich(doc: Doctor) -> Doctor:
            if not doc.profile_url:
                return doc
            html = fetch(session, doc.profile_url)
            if html:
                doc = parse_profile_page(html, doc)
            time.sleep(random.uniform(0.5, 1.5))
            return doc

        enriched = []
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_enrich, d): d for d in doctors}
            for f in as_completed(futures):
                enriched.append(f.result())
        doctors = enriched

    # Deduplicate
    seen: dict = {}
    for d in doctors:
        if d.nom_professionnel and d.nom_professionnel not in seen:
            seen[d.nom_professionnel] = d
    doctors = list(seen.values())

    mode = "a" if resume and seen_names else "w"
    with open(out, mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELD_NAMES)
        if mode == "w":
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

    logging.info(f"✅ Saved {len(doctors)} doctors → {out.resolve()}")
    progress_file = Path("data/scraping_progress.json")
    if progress_file.exists():
        progress_file.write_text(
            f'{{"current": {end - start + 1}, "total": {end - start + 1}, "doctors": {len(doctors)}, "done": true}}'
        )


def main():
    p = argparse.ArgumentParser(description="DabaDoc Scraper")
    p.add_argument("--pages",       nargs=2, type=int,   default=[1, 1297])
    p.add_argument("--delay",       nargs=2, type=float, default=[1.5, 3.5])
    p.add_argument("--output",      default="data/raw/dabadoc_raw.csv")
    p.add_argument("--workers",     type=int, default=3)
    p.add_argument("--deep-scrape", action="store_true", help="Fetch profile pages (address, GPS, avis, consultation types)")
    p.add_argument("--resume",      action="store_true")
    args = p.parse_args()
    scrape(args.pages[0], args.pages[1], tuple(args.delay), args.workers, args.deep_scrape, args.output, args.resume)


if __name__ == "__main__":
    main()
