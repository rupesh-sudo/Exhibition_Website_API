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
# ROUTER: detects the right scraper by HTML structure, not URL/domain
# ============================================================
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

    if "exhibitors__container-list" in html and "my-modal" in html:
        return "ptak_warsaw"

    return None


def route_scraper(url):
    template = detect_template(url)

    if template == "ptak_warsaw":
        return {"supported": True, "template": "ptak_warsaw", "data": scrape_ptak_warsaw(url)}

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
