import time

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
    # Block images to save memory and speed up loading - we don't need them
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

    # Fallback: look for any button/link containing common accept-cookie wording
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


def scrape_exhibitors(url):
    driver = get_driver()
    data = []
    try:
        driver.get(url)
        wait = WebDriverWait(driver, 15)

        # Dismiss any cookie banner before interacting with the page
        dismiss_cookie_banner(driver)

        wait.until(
            EC.presence_of_all_elements_located(
                (By.CSS_SELECTOR, ".exhibitors__container-list")
            )
        )

        exhibitors = driver.find_elements(By.CSS_SELECTOR, ".exhibitors__container-list")
        total = len(exhibitors)

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
                # Skip this exhibitor but keep going - one bad row shouldn't kill the run
                print(f"Skipped exhibitor {i}: {row_error}")
                continue
    finally:
        driver.quit()

    return data


@app.get("/")
def root():
    # Simple health check - hit this URL in a browser to confirm the service is live
    return {"status": "ok", "message": "Scraper API is running"}


@app.post("/scrape")
def scrape(req: ScrapeRequest):
    try:
        data = scrape_exhibitors(req.url)
        return JSONResponse(
            content={"count": len(data), "data": data},
            media_type="application/json; charset=utf-8",
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "count": 0, "data": []},
            media_type="application/json; charset=utf-8",
        )
