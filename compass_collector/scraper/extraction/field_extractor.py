import re
from typing import Optional
from datetime import datetime


class FieldExtractor:

    ORG_PATTERNS = [
        r"(?:McKinsey|BCG|Bain|Deloitte|PwC|EY|KPMG|Accenture)\s+(?:helped|worked with|partnered with|advised)\s+(?:a|an|the)?\s*(?:Fortune\s+\d+\s+)?([A-Z][A-Za-z\s&.,]{3,50}?(?:Inc|Corp|LLC|Ltd|Company|Co\.|Group|Partners|Systems|Technologies|Solutions|Services|Industries|Health|Financial|Bank|Insurance|Manufacturing|Logistics|Retail|Energy|Pharma|Automotive|Telecom|Airlines|Hospital|University|Institute|Agency|Department|Ministry|Authority|Association|Foundation|Center|Centre|Clinic|School|District|City|County|State|Federal|Government|Enterprises|Holdings|International|Global|Worldwide))",
        r"(?:a|an|the)?\s*(?:Fortune\s+\d+\s+)?([A-Z][A-Za-z\s&.,]{3,50}?(?:Inc|Corp|LLC|Ltd|Company|Co\.|Group|Partners|Systems|Technologies|Solutions|Services|Industries|Health|Financial|Bank|Insurance|Manufacturing|Logistics|Retail|Energy|Pharma|Automotive|Telecom|Airlines|Hospital|University|Institute|Agency|Department|Ministry|Authority|Association|Foundation|Center|Centre|Clinic|School|District|City|County|State|Federal|Government|Enterprises|Holdings|International|Global|Worldwide))\s+(?:implemented|deployed|adopted|rolled out|launched|introduced|automated|transformed|migrated|upgraded|engaged|partnered|reduced|increased|improved|saved|achieved|realized|gained|reported|announced)",
    ]

    INDUSTRY_KEYWORDS = {
        "healthcare": ["healthcare", "hospital", "clinic", "medical", "pharma", "patient"],
        "manufacturing": ["manufacturing", "factory", "production", "assembly", "industrial"],
        "finance": ["bank", "financial", "insurance", "investment", "credit", "lending"],
        "retail": ["retail", "e-commerce", "store", "consumer", "merchandise"],
        "technology": ["software", "tech", "SaaS", "platform", "cloud", "IT"],
        "logistics": ["logistics", "shipping", "warehouse", "supply chain", "transportation"],
        "energy": ["energy", "utility", "oil", "gas", "electric", "power"],
        "government": ["government", "federal", "state", "municipal", "public sector", "agency"],
        "education": ["university", "college", "school", "education", "academic"],
        "telecom": ["telecom", "telecommunications", "wireless", "broadband", "network"],
    }

    EMPLOYEE_BANDS = {
        "startup": (1, 50),
        "small": (51, 200),
        "mid-market": (201, 1000),
        "enterprise": (1001, 10000),
        "large enterprise": (10001, 50000),
        "global enterprise": (50001, float('inf')),
    }

    DURATION_PATTERNS = [
        r"(\d+)\s*(weeks?|months?|years?)\s*(?:implementation|deployment|project|rollout|migration)?",
        r"(?:implementation|deployment|project|rollout|migration|pilot)\s*(?:took|lasted|spanned|duration|timeline)?\s*(?:of\s*)?(\d+)\s*(weeks?|months?|years?)",
        r"(?:in|within|over)\s*(\d+)\s*(weeks?|months?|years?)",
    ]

    COST_PATTERNS = [
        r"(?:cost|investment|budget|spend|spent|price)\s*(?:of\s*)?[\$£€]?([\d,]+(?:\.\d+)?)\s*(million|billion|k|M|B|K)?",
        r"[\$£€]([\d,]+(?:\.\d+)?)\s*(million|billion|k|M|B|K)?\s*(?:implementation|project|deployment|investment|budget)?",
        r"(?:cost|investment|budget|spend)\s*(?:of\s*)?[\$£€]?([\d,]+(?:\.\d+)?)\s*(?:million|billion|k|M|B|K)",
        r"[\$£€]([\d,]+(?:\.\d+)?)\s*(million|billion|k|M|B|K)",
        r"cost\s*(?:of\s*)?[\$£€]?([\d,]+(?:\.\d+)?)\s*(million|billion|k|M|B|K)",
    ]

    BASELINE_PATTERNS = [
        r"(?:before|prior to|previously|originally|baseline|pre-implementation)\s*[,:]?\s*(?:was|were|had|averaged)?\s*(?:a\s*)?([\d,]+(?:\.\d+)?)\s*(?:hours?|days?|minutes?|seconds?|transactions?|calls?|tickets?|cases?|%|percent|FTE|agents?|employees?|staff)?",
        r"(?:from|starting at)\s*([\d,]+(?:\.\d+)?)\s*(?:hours?|days?|minutes?|transactions?|calls?|tickets?|cases?|%)",
    ]

    OUTCOME_PATTERNS = [
        r"(?:reduced|decreased|improved|increased|saved|achieved|gained|recovered|eliminated)\s*(?:by\s*)?([\d,]+(?:\.\d+)?)\s*(?:hours?|days?|minutes?|%|percent|dollars?|FTE|transactions?|calls?|tickets?)?",
        r"(?:to|down to|up to)\s*([\d,]+(?:\.\d+)?)\s*(?:hours?|days?|minutes?|%|percent|transactions?|calls?|tickets?)",
        r"([\d,]+(?:\.\d+)?)\s*(?:hours?|days?|%|percent)\s*(?:reduction|improvement|savings?|increase|decrease)",
        r"(?:savings?|reduction|improvement|increase|decrease)\s*(?:of\s*)?([\d,]+(?:\.\d+)?)\s*(?:hours?|days?|%|percent|dollars?|FTE)?",
    ]

    def extract_all(self, text: str) -> dict:
        text = text or ""
        return {
            "organization_name": self.extract_organization(text),
            "organization_industry": self.extract_industry(text),
            "organization_employee_count": self.extract_employee_count(text),
            "organization_employee_band": self._employee_band(text),
            "problem_business_function": self.extract_business_function(text),
            "problem_statement": self.extract_problem_statement(text),
            "intervention_implementation_cost": self.extract_cost(text),
            "intervention_implementation_time_value": self.extract_duration_value(text),
            "intervention_implementation_time_unit": self.extract_duration_unit(text),
            "baseline_value": self.extract_baseline(text),
            "outcome_value": self.extract_outcome(text),
            "outcome_percentage": self.extract_outcome_percentage(text),
            "has_baseline": self._has_baseline(text),
            "has_post_measurement": self._has_post_measurement(text),
            "has_control_group": self._has_control_group(text),
            "sample_size": self.extract_sample_size(text),
            "measurement_period": self.extract_measurement_period(text),
            "independently_verified": self._independently_verified(text),
            "vendor_reported": self._vendor_reported(text),
            "teams_involved": self.extract_teams(text),
            "software": self.extract_software(text),
            "success_factors": self.extract_success_factors(text),
            "failure_conditions": self.extract_failure_conditions(text),
        }

    def extract_organization(self, text: str) -> Optional[str]:
        for pattern in self.ORG_PATTERNS:
            match = re.search(pattern, text)
            if match:
                org = match.group(1).strip()
                if 3 < len(org) < 100 and not org.lower().startswith(("the ", "a ", "an ")):
                    return org
        return None

    def extract_industry(self, text: str) -> list[str]:
        text_lower = text.lower()
        industries = []
        for industry, keywords in self.INDUSTRY_KEYWORDS.items():
            for kw in keywords:
                if kw in text_lower:
                    industries.append(industry)
                    break
        return industries

    def extract_employee_count(self, text: str) -> Optional[int]:
        patterns = [
            r"(\d[\d,]*)\s*(?:employees?|people|staff|headcount|workers?|agents?|FTE)",
            r"(?:team|staff|workforce|organization|company)\s*(?:of\s*)?(\d[\d,]*)",
            r"(\d[\d,]*)\s*(?:person|employee|agent)\s+(?:team|organization|company)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return int(match.group(1).replace(",", ""))
                except ValueError:
                    continue
        return None

    def _employee_band(self, text: str) -> Optional[str]:
        count = self.extract_employee_count(text)
        if not count:
            return None
        for band, (low, high) in self.EMPLOYEE_BANDS.items():
            if low <= count <= high:
                return band
        return None

    def extract_business_function(self, text: str) -> list[str]:
        functions = {
            "customer_support": ["customer support", "customer service", "call center", "help desk", "contact center"],
            "finance": ["finance", "accounting", "accounts payable", "accounts receivable", "payroll", "billing", "invoice"],
            "operations": ["operations", "supply chain", "logistics", "manufacturing", "production", "warehouse", "inventory"],
            "human_resources": ["HR", "human resources", "recruiting", "hiring", "onboarding", "talent", "workforce"],
            "sales": ["sales", "revenue", "lead", "pipeline", "CRM", "customer acquisition"],
            "marketing": ["marketing", "advertising", "campaign", "brand", "content"],
            "it": ["IT", "infrastructure", "software", "development", "engineering", "DevOps", "cloud"],
            "legal": ["legal", "contract", "compliance", "regulatory", "risk", "audit"],
            "procurement": ["procurement", "purchasing", "sourcing", "vendor management", "supplier"],
        }
        text_lower = text.lower()
        found = []
        for func, keywords in functions.items():
            for kw in keywords:
                if kw in text_lower:
                    found.append(func)
                    break
        return found

    def extract_problem_statement(self, text: str) -> str:
        patterns = [
            r"(?:problem|challenge|issue|pain point|bottleneck)\s*[,:]?\s*(.{10,200})",
            r"(?:struggling|struggled|facing|faced)\s*(?:with\s*)?(.{10,200})",
            r"(?:before|prior to)\s*(?:the\s*)?(?:implementation|intervention|project|deployment)\s*[,:]?\s*(.{10,200})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                return match.group(1).strip()
        sentences = text.split(".")
        for s in sentences[:5]:
            if any(kw in s.lower() for kw in ["problem", "challenge", "issue", "bottleneck", "struggled", "manual", "time-consuming", "inefficient"]):
                return s.strip()
        return sentences[0].strip() if sentences else ""

    def extract_cost(self, text: str) -> Optional[float]:
        for pattern in self.COST_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                val_str = match.group(1).replace(",", "")
                multiplier = match.group(2).lower() if match.group(2) else ""
                try:
                    val = float(val_str)
                    if "million" in multiplier or "m" == multiplier:
                        val *= 1_000_000
                    elif "billion" in multiplier or "b" == multiplier:
                        val *= 1_000_000_000
                    elif "k" == multiplier:
                        val *= 1_000
                    return val
                except ValueError:
                    continue
        return None

    def extract_duration_value(self, text: str) -> Optional[float]:
        for pattern in self.DURATION_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1))
                except (ValueError, IndexError):
                    continue
        return None

    def extract_duration_unit(self, text: str) -> Optional[str]:
        for pattern in self.DURATION_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match and len(match.groups()) >= 2:
                return match.group(2).rstrip("s")
        return None

    def extract_baseline(self, text: str) -> Optional[float]:
        for pattern in self.BASELINE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1).replace(",", ""))
                except ValueError:
                    continue
        return None

    def extract_outcome(self, text: str) -> Optional[float]:
        for pattern in self.OUTCOME_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1).replace(",", ""))
                except ValueError:
                    continue
        return None

    def extract_outcome_percentage(self, text: str) -> Optional[float]:
        patterns = [
            r"([\d,]+(?:\.\d+)?)\s*%\s*(?:of\s*)?(?:reduction|improvement|savings?|increase|decrease|gain)",
            r"(?:reduced|decreased|improved|increased|saved)\s*(?:by\s*)?([\d,]+(?:\.\d+)?)\s*%",
            r"([\d,]+(?:\.\d+)?)\s*(?:percent|percentage)\s*(?:reduction|improvement|savings?|increase|decrease)",
            r"([\d,]+(?:\.\d+)?)\s*%",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1).replace(",", ""))
                except ValueError:
                    continue
        return None

    def _has_baseline(self, text: str) -> bool:
        return bool(re.search(
            r"baseline|before|pre-implementation|previously|originally|starting (?:at|with|from)"
            r"|(?:took|averaged|was|were|had)\s+[\d,]+(?:\.\d+)?\s*(?:hours?|days?|minutes?|transactions?|calls?|tickets?|%)"
            r"|from\s+[\d,]+(?:\.\d+)?\s*(?:hours?|days?|minutes?|transactions?|calls?|tickets?|%)",
            text, re.IGNORECASE
        ))

    def _has_post_measurement(self, text: str) -> bool:
        return bool(re.search(
            r"after|post-implementation|following|subsequently|measured|results|outcome"
            r"|(?:reduced|decreased|improved|increased|saved|dropped|fell)\s+(?:to|by|from)\s+[\d,]+",
            text, re.IGNORECASE
        ))

    def _has_control_group(self, text: str) -> bool:
        return bool(re.search(r"control group|comparison group|randomized|RCT|experimental design", text, re.IGNORECASE))

    def extract_sample_size(self, text: str) -> Optional[int]:
        patterns = [
            r"(?:sample|n|N|participants|organizations?|companies?|sites?|locations?)\s*(?:of|=|:)?\s*(\d[\d,]*)",
            r"(\d[\d,]*)\s*(?:organizations?|companies?|sites?|locations?|participants?|teams?|agents?|employees?)",
            r"(\d+)\s*(?:pilot|study|trial)\s*(?:sites?|organizations?|companies?)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return int(match.group(1).replace(",", ""))
                except ValueError:
                    continue
        return None

    def extract_measurement_period(self, text: str) -> Optional[str]:
        patterns = [
            r"(\d+)\s*(?:month|year|week|quarter)\s*(?:measurement|observation|study|follow-up|post-implementation)",
            r"(?:measured|tracked|observed|monitored)\s*(?:over|for)\s*(\d+)\s*(?:months?|years?|weeks?)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0)
        return None

    def _independently_verified(self, text: str) -> bool:
        return bool(re.search(r"independent|third[- ]party|audit|verified|peer[- ]reviewed|published|academic", text, re.IGNORECASE))

    def _vendor_reported(self, text: str) -> bool:
        return bool(re.search(r"vendor|partner|sponsored|case study by|customer success story|white paper", text, re.IGNORECASE))

    def extract_teams(self, text: str) -> list[str]:
        patterns = [
            r"(?:team|group|department|unit)\s*(?:of\s*)?(\d+)\s*(?:people|members?|staff|agents?|employees?)?",
            r"(?:involved|engaged|assigned|dedicated)\s*(\d+)\s*(?:team|group|people|members?|staff)",
        ]
        teams = []
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                teams.append(match.group(0))
        return teams

    def extract_software(self, text: str) -> list[str]:
        software_keywords = [
            "Salesforce", "SAP", "Oracle", "Microsoft", "Google", "AWS", "Azure",
            "ServiceNow", "Workday", "HubSpot", "Zendesk", "Slack", "Zoom",
            "Tableau", "Power BI", "Looker", "Snowflake", "Databricks",
            "TensorFlow", "PyTorch", "OpenAI", "GPT", "LLM", "RPA",
            "UiPath", "Automation Anywhere", "Blue Prism", "Zapier",
            "Python", "Java", "JavaScript", "SQL", "NoSQL",
        ]
        found = []
        for sw in software_keywords:
            if sw.lower() in text.lower():
                found.append(sw)
        return found

    def extract_success_factors(self, text: str) -> list[str]:
        factors = []
        patterns = [
            r"(?:success|key|critical|important)\s*(?:factor|reason|driver|enabler)\s*[,:]?\s*(.{10,100})",
            r"(?:worked|succeeded|effective)\s*(?:because|due to|thanks to)\s*(.{10,100})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                factors.append(match.group(1).strip())
        return factors

    def extract_failure_conditions(self, text: str) -> list[str]:
        conditions = []
        patterns = [
            r"(?:failed|failure|abandoned|cancelled|unsuccessful)\s*(?:because|due to|reason|factor)\s*[,:]?\s*(.{10,100})",
            r"(?:didn't work|did not work|failed)\s*(?:because|due to|when|after)\s*(.{10,100})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                conditions.append(match.group(1).strip())
        return conditions
