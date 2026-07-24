import feedparser
from .base_scraper import BaseScraper


class ArxivScraper(BaseScraper):

    CATEGORIES = ["cs.AI", "cs.LG", "cs.CY", "cs.DB", "cs.SE", "econ.GN", "econ.Q-fin"]

    KEYWORDS = [
        "implementation", "deployment", "case study", "enterprise",
        "ROI", "return on investment", "cost savings", "efficiency",
        "automation", "process improvement", "organizational",
        "workforce", "digital transformation", "change management",
        "adoption", "implementation failure", "lessons learned",
    ]

    def search(self, query: str, max_results: int = 50) -> list[dict]:
        feed_url = (
            f"http://export.arxiv.org/api/query?"
            f"search_query=all:{query.replace(' ', '+')}"
            f"&max_results={max_results}"
        )
        feed = feedparser.parse(feed_url)
        results = []
        for entry in feed.entries:
            results.append({
                "url": entry.get("link", ""),
                "title": entry.get("title", ""),
                "summary": entry.get("summary", ""),
                "authors": [a.get("name", "") for a in entry.get("authors", [])],
                "published": entry.get("published", ""),
                "categories": [t.get("term", "") for t in entry.get("tags", [])],
                "source_type": "academic",
                "publisher": "arXiv",
            })
        return results

    def search_by_keywords(self, max_per_keyword: int = 20) -> list[dict]:
        all_results = []
        for kw in self.KEYWORDS:
            results = self.search(kw, max_per_keyword)
            for r in results:
                r["search_keyword"] = kw
            all_results.extend(results)
        return all_results

    def get_paper_details(self, url: str) -> dict:
        soup = self.fetch_soup(url)
        abstract = soup.find("blockquote", class_="abstract")
        authors = [a.get_text() for a in soup.find_all("div", class_="authors")]
        return {
            "abstract": abstract.get_text() if abstract else "",
            "authors": authors,
        }
