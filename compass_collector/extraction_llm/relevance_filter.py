import re
from collections import Counter


class RelevanceFilter:

    HIGH_SIGNALS = [
        r"\bimplemented\b", r"\bdeployed\b", r"\bintroduced\b", r"\bredesigned\b",
        r"\bautomated\b", r"\bmigrated\b", r"\badopted\b", r"\bpiloted\b",
        r"\brolled\s*out\b", r"\blaunched\b", r"\btransformed\b",
        r"\breduced\b", r"\bincreased\b", r"\bsaved\b", r"\bgenerated\b",
        r"\bimproved\b", r"\bfailed\b", r"\babandoned\b",
        r"\bROI\b", r"\bpayback\b", r"\bcost\s*savings\b",
        r"\bhours?\s*saved\b", r"\bcycle\s*time\b", r"\bresponse\s*time\b",
        r"\berror\s*rate\b", r"\bconversion\s*rate\b", r"\bproductivity\b",
        r"\befficiency\b", r"\bthroughput\b", r"\bcapacity\b",
        r"\brevenue\b", r"\bprofit\b", r"\bmargin\b",
        r"\bcase\s*study\b", r"\bresults?\b", r"\boutcomes?\b",
        r"\b(?:before|after|baseline|post|pre)\b",
        r"\bdollar[s]?\b", r"\$[\d,]", r"\bpercent\b", r"%",
        r"\bteam\b", r"\bproject\b", r"\binvestment\b",
        r"\bpilot\b", r"\btrial\b", r"\bexperiment\b",
        r"\bstaff(?:ing|ed)?\b", r"\bhired\b", r"\boutsourced\b",
        r"\boffshored\b", r"\bcenter\s*of\s*excellence\b",
        r"\bgovernance\b", r"\bcompliance\b", r"\bpolicy\b",
    ]

    ORGANIZATION_SIGNALS = [
        r"\b(?:at|for|by|with)\s+[A-Z][a-zA-Z]+",  # "at Google", "by McKinsey"
        r"\b(?:Inc|Corp|LLC|Ltd|Company|Co\.|Group|Partners)\b",
        r"\b(?:University|College|Institute|School|Department)\b",
        r"\b(?:Hospital|Clinic|Medical|Health)\b",
        r"\b(?:Bank|Insurance|Financial)\b",
        r"\b(?:Government|Agency|Ministry|Department|City|County|State|Federal)\b",
        r"\b(?:Startup|Enterprise|Vendor|Consulting|Firm)\b",
        r"\b(?:Company|Corporation|Organization)\b",
    ]

    OUTCOME_SIGNALS = [
        r"\d+%", r"\$[\d,]+(?:\.\d+)?", r"\d+x\b",
        r"(?:reduced|increased|decreased|improved|saved|dropped|fell|rose)\s+",
        r"(?:from|to)\s+\$?[\d,]+",
        r"[\d,]+(?:\.\d+)?\s*(?:hours?|days?|weeks?|months?|years?)",
        r"[\d,]+(?:\.\d+)?\s*(?:FTE|employees?|people|staff|agents?)",
        r"[\d,]+(?:\.\d+)?\s*(?:transactions?|calls?|tickets?|cases?|orders?)",
    ]

    INTERVENTION_SIGNALS = [
        r"\b(?:AI|ML|RPA|ERP|CRM|BI|API|SaaS|IaaS|PaaS)\b",
        r"\b(?:automation|robot|chatbot|copilot|agent|workflow)\b",
        r"\b(?:software|platform|system|tool|solution|application)\b",
        r"\b(?:cloud|migrate|migration|digital)\b",
        r"\b(?:process|workflow|operation)\s*(?:redesign|reengineer|improve|optimize|simplif)\b",
        r"\b(?:training|upskill|reskill|workshop|certification)\b",
        r"\b(?:outsource|offshore|managed\s*services)\b",
        r"\b(?:governance|policy|compliance|framework)\b",
        r"\b(?:restructure|reorganize|reorg|consolidate)\b",
        r"\b(?:dashboard|reporting|analytics|KPI|metric)\b",
    ]

    EXCLUDE_PATTERNS = [
        r"^\s*$", r"^\{", r"^<", r"^#", r"^\/\/",
        r"(?:login|signup|subscribe|password|cookie)",
        r"(?:job\s*(?:posting|listing|opening|requisition))",
        r"(?:spam|scam|phishing)",
        r"(?:404|not\s*found|page\s*not\s*found)",
    ]

    def classify(self, title: str, text: str, url: str = "") -> dict:
        title_lower = (title or "").lower()
        text_lower = (text or "").lower()
        combined = title + " " + (text or "")
        combined_lower = combined.lower()

        high_matches = sum(1 for p in self.HIGH_SIGNALS if re.search(p, combined, re.IGNORECASE))
        org_matches = sum(1 for p in self.ORGANIZATION_SIGNALS if re.search(p, combined))
        outcome_matches = sum(1 for p in self.OUTCOME_SIGNALS if re.search(p, combined))
        intervention_matches = sum(1 for p in self.INTERVENTION_SIGNALS if re.search(p, combined, re.IGNORECASE))
        exclude_matches = sum(1 for p in self.EXCLUDE_PATTERNS if re.search(p, combined_lower))

        total_signals = high_matches + org_matches + outcome_matches + intervention_matches
        word_count = len(combined.split())

        if exclude_matches > 0:
            return {"label": "not_relevant", "confidence": 0.9,
                    "reason": f"Exclude pattern matched ({exclude_matches})",
                    "signals": {"high": high_matches, "org": org_matches,
                                "outcome": outcome_matches, "intervention": intervention_matches}}

        if total_signals >= 8 and org_matches >= 1 and outcome_matches >= 1 and intervention_matches >= 1:
            return {"label": "high_relevance", "confidence": 0.9,
                    "reason": f"Strong signals: {total_signals} total ({high_matches} high, {org_matches} org, {outcome_matches} outcome, {intervention_matches} intervention)",
                    "signals": {"high": high_matches, "org": org_matches,
                                "outcome": outcome_matches, "intervention": intervention_matches}}

        if total_signals >= 5 and (org_matches >= 1 or outcome_matches >= 1):
            return {"label": "high_relevance", "confidence": 0.7,
                    "reason": f"Moderate signals: {total_signals} total",
                    "signals": {"high": high_matches, "org": org_matches,
                                "outcome": outcome_matches, "intervention": intervention_matches}}

        if total_signals >= 3 and word_count >= 100:
            return {"label": "possible_relevance", "confidence": 0.5,
                    "reason": f"Weak signals: {total_signals} total, {word_count} words",
                    "signals": {"high": high_matches, "org": org_matches,
                                "outcome": outcome_matches, "intervention": intervention_matches}}

        return {"label": "not_relevant", "confidence": 0.7,
                "reason": f"Insufficient signals: {total_signals} total, {word_count} words",
                "signals": {"high": high_matches, "org": org_matches,
                            "outcome": outcome_matches, "intervention": intervention_matches}}

    def classify_all(self, records: list) -> list:
        results = []
        for rec in records:
            classification = self.classify(
                rec.get("title", ""),
                rec.get("text", ""),
                rec.get("url", "")
            )
            results.append({
                "record_id": rec.get("id"),
                "title": rec.get("title", "")[:100],
                "classification": classification["label"],
                "confidence": classification["confidence"],
                "reason": classification["reason"],
                "signals": classification["signals"],
            })
        return results
