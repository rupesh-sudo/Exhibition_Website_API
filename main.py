import time

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
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

    # Chrome options for Render
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--window-size=1920,1080")

    options.binary_location = "/usr/bin/google-chrome"

    service = Service(ChromeDriverManager().install())

    return webdriver.Chrome(service=service, options=options)


def scrape_exhibitors(url):
    driver = get_driver()
    data = []

    try:
        driver.get(url)

        # Wait for page to completely load
        WebDriverWait(driver, 60).until(
            lambda d: d.execute_script(
                "return document.readyState"
            ) == "complete"
        )

        # Extra buffer for slower Render instances
        time.sleep(5)

        wait = WebDriverWait(driver, 60)

        # Wait until exhibitor cards are visible
        wait.until(
            EC.presence_of_all_elements_located(
                (By.CSS_SELECTOR, ".exhibitors__container-list")
            )
        )

        exhibitors = driver.find_elements(
            By.CSS_SELECTOR,
            ".exhibitors__container-list"
        )

        total = len(exhibitors)

        print(f"Found {total} exhibitors.")

        for i in range(total):

            try:
                # Refresh the element list every iteration
                exhibitors = driver.find_elements(
                    By.CSS_SELECTOR,
                    ".exhibitors__container-list"
                )

                exhibitor = exhibitors[i]

                # Scroll into view
                driver.execute_script(
                    "arguments[0].scrollIntoView(true);",
                    exhibitor,
                )

                time.sleep(2)

                # Click exhibitor
                driver.execute_script(
                    "arguments[0].click();",
                    exhibitor,
                )

                # Give modal some time to start loading
                time.sleep(3)

                # Wait for modal
                wait.until(
                    EC.visibility_of_element_located(
                        (By.ID, "my-modal")
                    )
                )

                # Get exhibitor name
                try:
                    name = driver.find_element(
                        By.CSS_SELECTOR,
                        "#my-modal .modal__elements-text h3"
                    ).text.strip()

                except Exception:
                    name = ""

                # Get website
                try:
                    website = driver.find_element(
                        By.CSS_SELECTOR,
                        "#my-modal .modal__elements-text p b a"
                    ).get_attribute("href")

                except Exception:
                    website = ""

                data.append(
                    {
                        "name": name,
                        "website": website,
                        "source_url": url,
                    }
                )

                # Close modal
                try:
                    driver.find_element(
                        By.CSS_SELECTOR,
                        "#my-modal .close"
                    ).click()

                except Exception:
                    # Fallback if close button fails
                    driver.execute_script(
                        """
                        var modal = document.getElementById('my-modal');
                        if (modal) {
                            modal.style.display = 'none';
                        }
                        """
                    )

                time.sleep(2)

            except TimeoutException:
                print(
                    f"Timeout while loading modal for exhibitor index {i}"
                )

                # Useful for debugging on Render
                driver.save_screenshot(
                    f"/tmp/modal_timeout_{i}.png"
                )

                continue

            except Exception as e:
                print(
                    f"Error processing exhibitor index {i}: {e}"
                )

                driver.save_screenshot(
                    f"/tmp/error_{i}.png"
                )

                continue

    finally:
        driver.quit()

    return data


@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "Scraper API is running",
    }


@app.post("/scrape")
def scrape(req: ScrapeRequest):
    try:
        data = scrape_exhibitors(req.url)

        return JSONResponse(
            content={
                "success": True,
                "count": len(data),
                "data": data,
            },
            media_type="application/json; charset=utf-8",
        )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e),
            },
        )
