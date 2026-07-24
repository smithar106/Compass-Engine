import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time


class BaseScraper:

    def __init__(self, user_agent: str = "CompassCollector/1.0", rate_limit: float = 1.0):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self.rate_limit = rate_limit
        self._last_request = 0

    def _throttle(self):
        elapsed = time.time() - self._last_request
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)
        self._last_request = time.time()

    def fetch(self, url: str, timeout: int = 30) -> requests.Response:
        self._throttle()
        resp = self.session.get(url, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        return resp

    def fetch_soup(self, url: str, timeout: int = 30) -> BeautifulSoup:
        resp = self.fetch(url, timeout)
        return BeautifulSoup(resp.text, "html.parser")

    def extract_text(self, soup: BeautifulSoup) -> str:
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)

    def extract_links(self, soup: BeautifulSoup, base_url: str) -> list[str]:
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("http"):
                links.append(href)
            elif href.startswith("/"):
                links.append(urljoin(base_url, href))
        return list(set(links))

    def close(self):
        self.session.close()
