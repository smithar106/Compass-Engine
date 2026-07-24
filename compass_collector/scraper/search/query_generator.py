from itertools import product


class SearchQueryGenerator:

    PROBLEMS = [
        "manual reporting", "invoice processing", "customer support resolution",
        "call center wait times", "supply chain forecasting", "inventory management",
        "employee onboarding", "document review", "contract analysis",
        "quality control inspection", "production scheduling", "demand planning",
        "accounts payable", "accounts receivable", "payroll processing",
        "compliance reporting", "risk assessment", "fraud detection",
        "predictive maintenance", "workforce scheduling", "sales forecasting",
        "lead qualification", "customer churn prediction", "pricing optimization",
        "logistics routing", "warehouse picking", "field service dispatch",
        "claims processing", "loan underwriting", "credit scoring",
        "patient scheduling", "clinical documentation", "medical coding",
        "network monitoring", "cybersecurity threat detection",
        "email triage", "meeting scheduling", "travel expense processing",
        "IT help desk tickets", "software testing", "code review",
        "data entry", "data migration", "data quality management",
        "regulatory filing", "tax preparation", "audit preparation",
        "performance review", "talent acquisition", "employee retention",
        "vendor management", "procurement optimization", "contract negotiation",
    ]

    INTERVENTIONS = [
        "process redesign", "workflow simplification", "RPA automation",
        "AI implementation", "machine learning", "chatbot deployment",
        "predictive analytics", "software implementation", "cloud migration",
        "ERP implementation", "CRM implementation", "BI tool deployment",
        "staffing increase", "staffing reallocation", "outsourcing",
        "managed services", "training program", "governance framework",
        "organizational restructuring", "policy change", "KPI dashboard",
        "rules engine", "decision automation", "natural language processing",
        "computer vision", "robotic process automation", "intelligent automation",
        "generative AI", "large language model", "copilot deployment",
        "hybrid automation", "human-in-the-loop AI", "center of excellence",
    ]

    OUTCOMES = [
        "case study", "results", "outcomes", "ROI", "savings",
        "cost reduction", "time savings", "efficiency gain",
        "implementation", "deployment", "rollout", "adoption",
        "failed", "abandoned", "success", "improvement",
        "before and after", "lessons learned", "post-implementation",
    ]

    INDUSTRIES = [
        "manufacturing", "healthcare", "finance", "banking", "insurance",
        "retail", "logistics", "telecom", "energy", "government",
        "pharmaceutical", "automotive", "aerospace", "construction",
        "hospitality", "education", "legal", "accounting", "consulting",
    ]

    def generate_all(self) -> list[dict]:
        queries = []
        for problem, intervention, outcome in product(
            self.PROBLEMS[:20], self.INTERVENTIONS[:20], self.OUTCOMES[:10]
        ):
            query = f'"{problem}" {intervention} {outcome}'
            queries.append({
                "query": query,
                "problem": problem,
                "intervention": intervention,
                "outcome": outcome,
                "industry": None,
            })
        for problem, intervention, industry in product(
            self.PROBLEMS[:15], self.INTERVENTIONS[:15], self.INDUSTRIES[:10]
        ):
            query = f'"{problem}" {intervention} {industry} case study'
            queries.append({
                "query": query,
                "problem": problem,
                "intervention": intervention,
                "outcome": "case study",
                "industry": industry,
            })
        return queries

    def generate_failures(self) -> list[dict]:
        failure_queries = []
        failure_terms = ["failed", "abandoned", "cancelled", "over budget",
                         "underperformed", "reverted", "lessons learned",
                         "postmortem", "retrospective", "what went wrong"]
        for problem, term in product(self.PROBLEMS[:15], failure_terms):
            failure_queries.append({
                "query": f'"{problem}" {term}',
                "problem": problem,
                "intervention": None,
                "outcome": "failure",
                "industry": None,
            })
        return failure_queries

    def total_queries(self) -> int:
        return len(self.generate_all()) + len(self.generate_failures())
