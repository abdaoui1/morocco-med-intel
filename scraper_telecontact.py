#!/usr/bin/env python3
"""
scraper_telecontact.py — Telecontact.ma Doctor Scraper
=======================================================
URL pattern: /liens/{specialite}/{ville}.php?page=N
Output: data/raw/telecontact_raw.csv

Usage:
  python scraper_telecontact.py
  python scraper_telecontact.py --limit 200   # test rapide
"""

import re, csv, time, logging, argparse, random
from pathlib import Path
import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("telecontact")

BASE_URL    = "https://www.telecontact.ma"
OUTPUT      = Path("data/raw/telecontact_raw.csv")
FIELD_NAMES = ["nom_professionnel", "profile_url", "specialite", "ville", "adresse_complete", "source"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

SPECIALTIES = [
    ("medecins-generalistes",           "Médecin généraliste"),
    ("cardiologues",                    "Cardiologue"),
    ("dermatologues",                   "Dermatologue"),
    ("gynecologues",                    "Gynécologue"),
    ("pediatres",                       "Pédiatre"),
    ("ophtalmologues",                  "Ophtalmologue"),
    ("psychiatres",                     "Psychiatre"),
    ("neurologues",                     "Neurologue"),
    ("radiologues",                     "Radiologue"),
    ("rhumatologues",                   "Rhumatologue"),
    ("urologues",                       "Urologue"),
    ("pneumologues",                    "Pneumologue"),
    ("nephrologues",                    "Néphrologue"),
    ("gastro-enterologues",             "Gastro-entérologue"),
    ("endocrinologues",                 "Endocrinologue"),
    ("chirurgiens-orthopedistes",       "Chirurgien"),
    ("oto-rhino-laryngologistes",       "ORL"),
    ("dentistes",                       "Dentiste"),
    ("stomatologues",                   "Stomatologue"),
    ("medecins",                        "Médecin"),
]

CITIES = [
    "casablanca", "rabat", "marrakech", "fes", "tanger", "agadir",
    "kenitra", "meknes", "oujda", "sale", "temara", "tetouan",
    "mohammedia", "khouribga", "beni-mellal", "el-jadida", "nador",
    "settat", "safi", "khenifra", "berrechid", "khemisset", "larache",
    "inezgane", "taza", "ouarzazate", "laayoune", "guelmim", "tiznit",
    "errachidia", "berkane", "taourirt", "sidi-slimane", "sidi-kacem",
    "ouazzane", "al-hoceima", "ifrane", "azrou", "midelt", "tan-tan",
]


def fetch(session, url):
    for attempt in range(3):
        try:
            r = session.get(url, timeout=20)
            if r.status_code == 200:
                return r.text
            if r.status_code == 404:
                return None
        except requests.RequestException:
            pass
        time.sleep(3 * (attempt + 1))
    return None


def get_last_page(soup):
    last = 1
    for a in soup.select("a"):
        m = re.search(r"page=(\d+)", a.get("href", ""))
        if m:
            last = max(last, int(m.group(1)))
    return last


def parse_page(html, specialite_label, ville_label):
    soup = BeautifulSoup(html, "lxml")
    doctors = []

    for card in soup.select("div.result-search-item-profession"):
        name_tag = card.select_one("h2 a")
        if not name_tag:
            continue
        name = re.sub(r"\s+", " ", name_tag.get_text(strip=True))
        href = name_tag.get("href", "")
        url  = href if href.startswith("http") else BASE_URL + href

        addr_tag = card.select_one("p[itemprop='streetAddress']")
        addr = re.sub(r"\s+", " ", addr_tag.get_text(strip=True)) if addr_tag else ""
        addr = re.sub(r"\bMaroc\b", "", addr, flags=re.I).strip(" ,")

        doctors.append({
            "nom_professionnel": name,
            "profile_url": url,
            "specialite": specialite_label,
            "ville": ville_label,
            "adresse_complete": addr or "Non spécifiée",
            "source": "telecontact",
        })

    # Basic listing cards (no featured block)
    featured_names = {d["nom_professionnel"] for d in doctors}
    for h2 in soup.select("h2"):
        a = h2.find("a")
        if not a:
            continue
        name = re.sub(r"\s+", " ", a.get_text(strip=True))
        if not name or name in featured_names:
            continue
        href = a.get("href", "")
        url  = href if href.startswith("http") else BASE_URL + href

        # Address: next sibling p
        addr = ""
        parent = h2.find_parent()
        if parent:
            for p in parent.find_all("p"):
                txt = p.get_text(strip=True)
                if re.search(r"\d|rue|bd|av|lot|hay|quartier|imm", txt, re.I) and len(txt) > 10:
                    addr = re.sub(r"\bMaroc\b", "", txt, flags=re.I).strip(" ,")
                    break

        featured_names.add(name)
        doctors.append({
            "nom_professionnel": name,
            "profile_url": url,
            "specialite": specialite_label,
            "ville": ville_label,
            "adresse_complete": addr or "Non spécifiée",
            "source": "telecontact",
        })

    return doctors, get_last_page(soup)


def run(limit=None):
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(HEADERS)

    total = 0
    first_write = True
    seen_global = set()  # nom+ville global dedup

    for spec_slug, spec_label in SPECIALTIES:
        for city_slug in CITIES:
            city_label = city_slug.replace("-", " ").title()
            url = f"{BASE_URL}/liens/{spec_slug}/{city_slug}.php"

            html = fetch(session, url)
            if not html:
                continue

            doctors, last_page = parse_page(html, spec_label, city_label)
            log.info(f"{spec_label} / {city_label}: {last_page} pages, page 1 → {len(doctors)}")

            for d in doctors:
                key = d["nom_professionnel"].lower() + "_" + d["ville"].lower()
                if key not in seen_global:
                    seen_global.add(key)
                    _write([d], first_write)
                    first_write = False
                    total += 1

            # Pages 2..N
            for page in range(2, last_page + 1):
                if limit and total >= limit:
                    break
                html = fetch(session, f"{url}?page={page}")
                if not html:
                    continue
                page_docs, _ = parse_page(html, spec_label, city_label)
                new = 0
                for d in page_docs:
                    key = d["nom_professionnel"].lower() + "_" + d["ville"].lower()
                    if key not in seen_global:
                        seen_global.add(key)
                        _write([d], False)
                        total += 1
                        new += 1
                if new:
                    log.info(f"  page {page}/{last_page} → {new} nouveaux (total: {total})")
                time.sleep(random.uniform(0.8, 1.5))

            if limit and total >= limit:
                break
            time.sleep(random.uniform(1.0, 2.0))

        if limit and total >= limit:
            break

    log.info(f"✅ Done — {total} médecins → {OUTPUT}")


def _write(doctors, write_header):
    with open(OUTPUT, "w" if write_header else "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELD_NAMES)
        if write_header:
            writer.writeheader()
        writer.writerows(doctors)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args()
    run(args.limit)
