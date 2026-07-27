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
    options.binary_location = "/usr/bin/google-chrome"

    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def scrape_exhibitors(url):
    driver = get_driver()
    data = []
    try:
        driver.get(url)
        wait = WebDriverWait(driver, 15)
        wait.until(
            EC.presence_of_all_elements_located(
                (By.CSS_SELECTOR, ".exhibitors__container-list")
            )
        )

        exhibitors = driver.find_elements(By.CSS_SELECTOR, ".exhibitors__container-list")
        total = len(exhibitors)

        for i in range(total):
            exhibitors = driver.find_elements(By.CSS_SELECTOR, ".exhibitors__container-list")
            exhibitor = exhibitors[i]

            driver.execute_script("arguments[0].scrollIntoView(true);", exhibitor)
            time.sleep(1)
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
            time.sleep(1)
    finally:
        driver.quit()

    return data


@app.get("/")
def root():
    # Simple health check - hit this URL in a browser to confirm the service is live
    return {"status": "ok", "message": "Scraper API is running"}


@app.post("/scrape")
def scrape(req: ScrapeRequest):
    data = scrape_exhibitors(req.url)
    return JSONResponse(
        content={"count": len(data), "data": data},
        media_type="application/json; charset=utf-8",
    )
