import json
import time
from urllib.parse import quote_plus
from .base_scraper import BaseScraper


class WebSearchScraper(BaseScraper):

    def duckduckgo_search(self, query: str, max_results: int = 20) -> list[dict]:
        search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        soup = self.fetch_soup(search_url)
        results = []
        for result in soup.find_all("div", class_="result")[:max_results]:
            title_tag = result.find("a", class_="result__a")
            snippet_tag = result.find("a", class_="result__snippet")
            if title_tag:
                results.append({
                    "url": title_tag.get("href", ""),
                    "title": title_tag.get_text(strip=True),
                    "snippet": snippet_tag.get_text(strip=True) if snippet_tag else "",
                })
        return results

    def duckduckgo_instant(self, query: str) -> dict:
        api_url = f"https://api.duckduckgo.com/?q={quote_plus(query)}&format=json&no_redirect=1"
        resp = self.fetch(api_url)
        return resp.json()

    def bing_search(self, query: str, max_results: int = 20) -> list[dict]:
        search_url = f"https://www.bing.com/search?q={quote_plus(query)}&count={max_results}"
        soup = self.fetch_soup(search_url)
        results = []
        for li in soup.find_all("li", class_="b_algo")[:max_results]:
            h2 = li.find("h2")
            a = h2.find("a") if h2 else None
            p = li.find("p")
            if a:
                url = a.get("href", "")
                # Follow Bing redirect to get real URL
                if "bing.com/ck/a" in url:
                    try:
                        resp = self.fetch(url, timeout=10)
                        url = resp.url
                    except Exception:
                        pass
                results.append({
                    "url": url,
                    "title": a.get_text(strip=True),
                    "snippet": p.get_text(strip=True) if p else "",
                })
        return results


class RSSFeedScraper(BaseScraper):

    FEEDS = {
        "hbr": "https://hbr.org/feed",
        "mit_sloan": "https://sloanreview.mit.edu/feed/",
        "mckinsey": "https://www.mckinsey.com/insights/rss.aspx",
        "bcg": "https://www.bcg.com/rss/feed.xml",
        "bain": "https://www.bain.com/insights/rss/",
        "gartner": "https://www.gartner.com/en/newsroom/rss",
        "forrester": "https://www.forrester.com/blogs/feed/",
        "deloitte": "https://www2.deloitte.com/us/en/insights/rss.xml",
        "pwc": "https://www.pwc.com/us/en/insights/rss.xml",
        "ey": "https://www.ey.com/en_us/rss",
        "kpmg": "https://home.kpmg/us/en/home/insights/rss.html",
        "accenture": "https://www.accenture.com/us-en/insights/rss",
    }

    def fetch_feed(self, name: str, max_entries: int = 20) -> list[dict]:
        import feedparser
        url = self.FEEDS.get(name)
        if not url:
            return []
        feed = feedparser.parse(url)
        entries = []
        for entry in feed.entries[:max_entries]:
            entries.append({
                "url": entry.get("link", ""),
                "title": entry.get("title", ""),
                "summary": entry.get("summary", ""),
                "published": entry.get("published", ""),
                "publisher": name,
            })
        return entries

    def fetch_all_feeds(self, max_per_feed: int = 10) -> list[dict]:
        all_entries = []
        for name in self.FEEDS:
            try:
                entries = self.fetch_feed(name, max_per_feed)
                all_entries.extend(entries)
            except Exception as e:
                print(f"Failed to fetch {name}: {e}")
        return all_entries
