from .base_scraper import BaseScraper


class DirectSourceScraper(BaseScraper):

    SOURCES = [
        {
            "name": "McKinsey Operations",
            "url": "https://www.mckinsey.com/capabilities/operations/our-insights",
            "type": "consulting",
            "rss": "https://www.mckinsey.com/insights/rss.aspx",
        },
        {
            "name": "BCG Publications",
            "url": "https://www.bcg.com/publications",
            "type": "consulting",
            "rss": "https://www.bcg.com/rss/feed.xml",
        },
        {
            "name": "Bain Insights",
            "url": "https://www.bain.com/insights/",
            "type": "consulting",
            "rss": "https://www.bain.com/insights/rss/",
        },
        {
            "name": "Deloitte Insights",
            "url": "https://www2.deloitte.com/us/en/insights.html",
            "type": "consulting",
            "rss": "https://www2.deloitte.com/us/en/insights/rss.xml",
        },
        {
            "name": "HBR",
            "url": "https://hbr.org/topic/operations",
            "type": "academic",
            "rss": "https://hbr.org/feed",
        },
        {
            "name": "MIT Sloan",
            "url": "https://sloanreview.mit.edu/topic/operations-management/",
            "type": "academic",
            "rss": "https://sloanreview.mit.edu/feed/",
        },
        {
            "name": "Gartner",
            "url": "https://www.gartner.com/en/research",
            "type": "analyst",
            "rss": "https://www.gartner.com/en/newsroom/rss",
        },
        {
            "name": "Forrester",
            "url": "https://www.forrester.com/blogs/",
            "type": "analyst",
            "rss": "https://www.forrester.com/blogs/feed/",
        },
        {
            "name": "UiPath Case Studies",
            "url": "https://www.uipath.com/resources/automation-case-studies",
            "type": "vendor",
        },
        {
            "name": "Automation Anywhere Customers",
            "url": "https://www.automationanywhere.com/customers",
            "type": "vendor",
        },
        {
            "name": "Zapier Customer Stories",
            "url": "https://zapier.com/customers",
            "type": "vendor",
        },
        {
            "name": "Salesforce Customer Stories",
            "url": "https://www.salesforce.com/customer-success-stories/",
            "type": "vendor",
        },
        {
            "name": "ServiceNow Customer Outcomes",
            "url": "https://www.servicenow.com/customers.html",
            "type": "vendor",
        },
        {
            "name": "AWS Case Studies",
            "url": "https://aws.amazon.com/solutions/case-studies/",
            "type": "vendor",
        },
        {
            "name": "Microsoft Customer Stories",
            "url": "https://customers.microsoft.com/",
            "type": "vendor",
        },
        {
            "name": "Google Cloud Customers",
            "url": "https://cloud.google.com/customers",
            "type": "vendor",
        },
        {
            "name": "SAP Customer Stories",
            "url": "https://www.sap.com/customer-stories.html",
            "type": "vendor",
        },
        {
            "name": "Oracle Customer Success",
            "url": "https://www.oracle.com/customers/",
            "type": "vendor",
        },
        {
            "name": "Workday Customer Stories",
            "url": "https://www.workday.com/en-us/customers.html",
            "type": "vendor",
        },
        {
            "name": "HubSpot Case Studies",
            "url": "https://www.hubspot.com/case-studies",
            "type": "vendor",
        },
    ]

    def get_all_sources(self) -> list[dict]:
        return self.SOURCES

    def scrape_source(self, source: dict, max_pages: int = 3) -> list[dict]:
        results = []
        try:
            soup = self.fetch_soup(source["url"], timeout=15)
            text = self.extract_text(soup)
            links = self.extract_links(soup, source["url"])

            # Try to find case study / article links
            case_links = [l for l in links if any(
                kw in l.lower() for kw in [
                    "case-study", "case_study", "customer", "success",
                    "implementation", "result", "story", "insight",
                    "article", "publication", "report", "white-paper"
                ]
            )]

            for link in case_links[:max_pages]:
                try:
                    page_soup = self.fetch_soup(link, timeout=15)
                    page_text = self.extract_text(page_soup)
                    if len(page_text) > 500:
                        results.append({
                            "url": link,
                            "title": page_soup.title.string if page_soup.title else "",
                            "text": page_text,
                            "source_name": source["name"],
                            "source_type": source["type"],
                        })
                except Exception:
                    continue

            if not results and len(text) > 1000:
                results.append({
                    "url": source["url"],
                    "title": source["name"],
                    "text": text,
                    "source_name": source["name"],
                    "source_type": source["type"],
                })

        except Exception as e:
            print(f"  Failed to scrape {source['name']}: {e}")

        return results

    def scrape_all(self, max_per_source: int = 2) -> list[dict]:
        all_results = []
        for source in self.SOURCES:
            results = self.scrape_source(source, max_per_source)
            all_results.extend(results)
            print(f"  {source['name']}: {len(results)} pages")
        return all_results
