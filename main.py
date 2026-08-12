import time
from urllib.parse import urlparse

import requests

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

app = FastAPI()


class ScrapeRequest(BaseModel):
    url: str


# ============================================================
# SHARED: CHROME DRIVER SETUP
# ============================================================
def get_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--window-size=1280,800")
    options.add_argument("--remote-debugging-port=9222")
    options.add_experimental_option(
        "prefs", {"profile.managed_default_content_settings.images": 2}
    )
    options.binary_location = "/usr/bin/google-chrome"

    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def dismiss_cookie_banner(driver):
    """Try common cookie-consent button patterns. Safe to fail silently if none match."""
    common_selectors = [
        "button[data-action-type='accept']",
        "button#accept",
        "#onetrust-accept-btn-handler",
        "button#onetrust-accept-btn-handler",
        ".cc-btn.cc-allow",
        ".cookie-accept",
        "[class*='cookie'] button",
        "[id*='cookie'] button",
        "button[class*='accept']",
        "button[id*='accept']",
    ]
    for selector in common_selectors:
        try:
            btn = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
            )
            driver.execute_script("arguments[0].click();", btn)
            time.sleep(0.5)
            return True
        except Exception:
            continue

    keywords = ["accept", "zaakceptuj", "akceptuję", "zgadzam", "agree", "allow"]
    try:
        clickable = driver.find_elements(By.CSS_SELECTOR, "button, a")
        for el in clickable:
            text = (el.text or "").strip().lower()
            if any(k in text for k in keywords):
                driver.execute_script("arguments[0].click();", el)
                time.sleep(0.5)
                return True
    except Exception:
        pass

    return False


# ============================================================
# TEMPLATE: PWE EXPOPLANNER / PTAK WARSAW EXPO NETWORK
# (packagingpoland.pl, compositepoland.com, solarenergyexpo.com, etc.)
# ============================================================
def scrape_ptak_warsaw(url):
    driver = get_driver()
    data = []
    try:
        driver.get(url)
        wait = WebDriverWait(driver, 15)

        dismiss_cookie_banner(driver)

        wait.until(
            EC.presence_of_all_elements_located(
                (By.CSS_SELECTOR, ".exhibitors__container-list")
            )
        )

        exhibitors = driver.find_elements(By.CSS_SELECTOR, ".exhibitors__container-list")
        total = len(exhibitors)
        print(f"Total exhibitors found: {total}")

        for i in range(total):
            try:
                exhibitors = driver.find_elements(By.CSS_SELECTOR, ".exhibitors__container-list")
                exhibitor = exhibitors[i]

                driver.execute_script("arguments[0].scrollIntoView(true);", exhibitor)
                driver.execute_script("arguments[0].click();", exhibitor)

                wait.until(EC.visibility_of_element_located((By.ID, "my-modal")))

                try:
                    name = driver.find_element(
                        By.CSS_SELECTOR, "#my-modal .modal__elements-text h3"
                    ).text.strip()
                except Exception:
                    name = ""

                try:
                    website = driver.find_element(
                        By.CSS_SELECTOR, "#my-modal .modal__elements-text p b a"
                    ).get_attribute("href")
                except Exception:
                    website = ""

                data.append({"name": name, "website": website, "source_url": url})

                try:
                    driver.find_element(By.CSS_SELECTOR, "#my-modal .close").click()
                except Exception:
                    driver.execute_script(
                        "document.getElementById('my-modal').style.display='none';"
                    )
            except Exception as row_error:
                print(f"Skipped exhibitor {i}: {row_error}")
                continue
    finally:
        driver.quit()

    return data


# ============================================================
# TEMPLATE: ALGOLIA INSTANTSEARCH EXHIBITOR DIRECTORIES
# (groenesector.nl, empack-schweiz.ch, and similar sites sharing
#  the same underlying exhibitor-directory platform)
# ============================================================
LISTING_CARD_SELECTORS = [
    "li.ais-Hits-item article.card.hit__container",
    "li.ais-Hits-item",
]
CARD_LINK_SELECTORS = ["a.card__link", "a[href]"]
CARD_NAME_SELECTORS = ["h2", "h3"]


def collect_algolia_links(start_url, max_pages=25):
    driver = get_driver()
    links = []
    seen = set()

    try:
        driver.get(start_url)
        wait = WebDriverWait(driver, 15)
        dismiss_cookie_banner(driver)

        page_number = 1
        while True:
            cards = []
            for sel in LISTING_CARD_SELECTORS:
                try:
                    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
                    cards = driver.find_elements(By.CSS_SELECTOR, sel)
                    if cards:
                        break
                except Exception:
                    continue

            print(f"Page {page_number}: found {len(cards)} cards")

            for card in cards:
                profile_url = ""
                for lsel in CARD_LINK_SELECTORS:
                    try:
                        link_el = card.find_element(By.CSS_SELECTOR, lsel)
                        href = link_el.get_attribute("href")
                        if href:
                            profile_url = href.strip()
                            break
                    except Exception:
                        continue

                company_name = ""
                for nsel in CARD_NAME_SELECTORS:
                    try:
                        company_name = card.find_element(By.CSS_SELECTOR, nsel).text.strip()
                        if company_name:
                            break
                    except Exception:
                        continue

                if profile_url and profile_url not in seen:
                    seen.add(profile_url)
                    links.append({"company_name": company_name, "profile_link": profile_url})

            # Find and follow next-page link
            next_elements = driver.find_elements(
                By.CSS_SELECTOR, "li.ais-Pagination-item--nextPage a"
            )
            if not next_elements:
                break

            next_button = next_elements[0]
            try:
                parent_li = next_button.find_element(By.XPATH, "./..")
                if "ais-Pagination-item--disabled" in (parent_li.get_attribute("class") or ""):
                    break
            except Exception:
                pass

            next_url = (next_button.get_attribute("href") or "").strip()
            if not next_url or page_number >= max_pages:
                break

            page_number += 1
            driver.get(next_url)
            time.sleep(1)
    finally:
        driver.quit()

    return links


def scrape_algolia_family(start_url):
    links = collect_algolia_links(start_url)
    print(f"Total exhibitor profile links found: {len(links)}")

    driver = get_driver()
    data = []
    wait = WebDriverWait(driver, 20)

    try:
        for item in links:
            profile_url = item["profile_link"]
            try:
                driver.get(profile_url)
                wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "h1.stand-details__title"))
                )
                time.sleep(1)

                try:
                    name = driver.find_element(
                        By.CSS_SELECTOR, "h1.stand-details__title"
                    ).text.strip()
                except Exception:
                    name = item.get("company_name", "")
                if not name:
                    name = item.get("company_name", "")

                address = ""
                try:
                    for el in driver.find_elements(
                        By.CSS_SELECTOR, "div.contact-info-card__info-line-content"
                    ):
                        text = el.text.strip()
                        if text and not text.startswith("http") and "@" not in text and "www." not in text.lower():
                            address = text
                            break
                except Exception:
                    pass

                website = ""
                social_sites = [
                    "linkedin.com", "facebook.com", "instagram.com", "twitter.com",
                    "x.com", "youtube.com", "tiktok.com", "pinterest.com", "whatsapp.com",
                ]
                website_selectors = [
                    "div.contact-info-card__info-line-content a",
                    "div.contact-info-card__info-line a",
                    "section.card.contact-info-card a[href^='http']",
                ]
                for wsel in website_selectors:
                    try:
                        for link_el in driver.find_elements(By.CSS_SELECTOR, wsel):
                            href = (link_el.get_attribute("href") or "").strip()
                            if not href:
                                continue
                            href_lower = href.lower()
                            if any(s in href_lower for s in social_sites):
                                continue
                            if urlparse(start_url).netloc.lower() in href_lower:
                                continue
                            website = href
                            break
                    except Exception:
                        continue
                    if website:
                        break

                data.append({
                    "name": name,
                    "address": address,
                    "website": website,
                    "source_url": profile_url,
                })
            except Exception as row_error:
                print(f"Skipped {profile_url}: {row_error}")
                continue
    finally:
        driver.quit()

    return data



def detect_template(url):
    """Fetch raw HTML and check for signature markers unique to each known template."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/138.0.0.0 Safari/537.36"
        )
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        html = response.text
    except Exception:
        html = ""

    if "exhibitors__container-list" in html:
        return "ptak_warsaw"

    if "ais-Hits-item" in html or "ais-Pagination" in html:
        return "algolia_family"

    return None


def route_scraper(url):
    template = detect_template(url)

    if template == "ptak_warsaw":
        return {"supported": True, "template": "ptak_warsaw", "data": scrape_ptak_warsaw(url)}

    if template == "algolia_family":
        return {"supported": True, "template": "algolia_family", "data": scrape_algolia_family(url)}

    return {
        "supported": False,
        "data": [],
        "message": (
            "No scraper template exists yet for this website's structure. "
            "Add a new template: inspect the exhibitor listing HTML, add a "
            "detection signature to detect_template(), and write a matching "
            "scrape_<platform_name>() function in main.py."
        ),
    }


# ============================================================
# API ENDPOINTS
# ============================================================
@app.get("/")
def root():
    return {"status": "ok", "message": "Scraper API is running"}


@app.post("/scrape")
def scrape(req: ScrapeRequest):
    start_time = time.time()

    try:
        result = route_scraper(req.url)
        elapsed_seconds = time.time() - start_time
        elapsed_minutes = round(elapsed_seconds / 60, 2)

        if not result["supported"]:
            return JSONResponse(
                status_code=200,
                content={
                    "supported": False,
                    "count": 0,
                    "data": [],
                    "message": result["message"],
                    "time_taken_minutes": elapsed_minutes,
                },
                media_type="application/json; charset=utf-8",
            )

        data = result["data"]
        return JSONResponse(
            content={
                "supported": True,
                "template": result["template"],
                "count": len(data),
                "data": data,
                "time_taken_minutes": elapsed_minutes,
            },
            media_type="application/json; charset=utf-8",
        )
    except Exception as e:
        elapsed_seconds = time.time() - start_time
        elapsed_minutes = round(elapsed_seconds / 60, 2)
        return JSONResponse(
            status_code=500,
            content={
                "error": str(e),
                "count": 0,
                "data": [],
                "time_taken_minutes": elapsed_minutes,
            },
            media_type="application/json; charset=utf-8",
        )
