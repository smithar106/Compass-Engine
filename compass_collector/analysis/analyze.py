"""Shared Analyze pathway logic: deterministic normalization, text inference,
and adaptive follow-up selection. This mirrors the web client's behavior so the
engine and the website produce equivalent decisions. Pure functions, no I/O.
"""

import re
from typing import Any, Dict, List, Set

WORKFLOW_MAP: List[Dict[str, str]] = [
    {"match": r"invoice|payable|payments|billing|reconciliation|procurement|\bap\b", "workflow": "invoice_processing", "businessFunction": "finance"},
    {"match": r"onboard|customer setup|welcome|kickoff|implementation.*customer", "workflow": "onboarding", "businessFunction": "customer_success"},
    {"match": r"support|ticket|escalat|complaint|help ?desk|service ?desk", "workflow": "ticketing", "businessFunction": "support"},
    {"match": r"contract|legal|clause|agreement|mnda", "workflow": "contract_review", "businessFunction": "legal"},
    {"match": r"lead|sales|qualif|prospecting|pipeline", "workflow": "lead_qualification", "businessFunction": "sales"},
    {"match": r"marketing|campaign|lead nurturing|email.*campaign", "workflow": "marketing_automation", "businessFunction": "marketing"},
    {"match": r"ci ?cd|deploy|release|build.*test", "workflow": "ci_cd", "businessFunction": "engineering"},
    {"match": r"knowledge|spreadsheet|tribal|documentation|information|search", "workflow": "process_automation", "businessFunction": "operations"},
    {"match": r"report|reporting|dashboard|kpi|metric|monthly close|reconcil", "workflow": "process_automation", "businessFunction": "finance"},
    {"match": r"manufactur|production|assembly|warehouse|quality.*line", "workflow": "manufacturing", "businessFunction": "operations"},
    {"match": r"supply|inventory|logistics|fulfil", "workflow": "supply_chain", "businessFunction": "operations"},
]

DEFAULT = {"workflow": "process_automation", "businessFunction": "operations"}

ROOT_CAUSE_TEMPLATES: Dict[str, str] = {
    "invoice_processing": "Manual receipt, validation, and matching steps with no structured routing; exceptions are handled individually, so cost and error rate scale with volume.",
    "onboarding": "Manual intake and handoffs across approvals and system setup; no standardized sequence, so cycle time depends on whoever happens to be available.",
    "ticketing": "Escalation triage is manual and unstandardized; routing depends on experience, so high-priority items wait and resolution time is inconsistent.",
    "contract_review": "Contract review is serial and human-only; clauses are checked one document at a time with no extraction or queueing, so backlog compounds.",
    "lead_qualification": "Leads arrive through multiple channels and are qualified by hand with no scoring criteria, so response time and follow-up consistency suffer.",
    "marketing_automation": "Campaigns are assembled and sent as single broadcasts; no segmentation or triggers, so engagement and conversion stay below what the channel supports.",
    "ci_cd": "Build, test, and deploy steps are manual and unautomated, so releases are slow, risky, and dependent on specific individuals.",
    "process_automation": "Work relies on manual steps and tribal knowledge with no single source of truth, so effort repeats and answers vary by person.",
    "manufacturing": "Line and quality processes have manual checkpoints with limited instrumentation, so defects surface late and throughput is inconsistent.",
    "supply_chain": "Inventory and logistics coordination is manual across systems, so stockouts and delays follow from slow, error-prone handoffs.",
}


def infer_desired_outcome(text: str) -> str:
    t = text.lower()
    if re.search(r"(cost|expensive|spend|budget|overhead|saving|save money)", t):
        return "cost"
    if re.search(r"(time|slow|delay|cycle|long|wait|faster|days)", t):
        return "time"
    if re.search(r"(error|mistake|quality|rework|defect|accuracy|incorrect)", t):
        return "quality"
    if re.search(r"(revenue|sell|convert|grow|acquisition|churn)", t):
        return "revenue"
    if re.search(r"(compliance|regulat|audit)", t):
        return "compliance"
    if re.search(r"(capacity|scale|volume|throughput|productivity|manual work)", t):
        return "efficiency"
    return "efficiency"


def root_cause_for(workflow: str) -> str:
    return ROOT_CAUSE_TEMPLATES.get(
        workflow, "A manual, unstandardized workflow with no automation; effort and errors scale with volume."
    )


def normalize_problem(text: str) -> Dict[str, str]:
    clean = text.strip()
    lower = clean.lower()
    match = dict(DEFAULT)
    for m in WORKFLOW_MAP:
        if re.search(m["match"], lower):
            match = {"workflow": m["workflow"], "businessFunction": m["businessFunction"]}
            break
    desired_outcome = infer_desired_outcome(clean)
    return {
        "workflow": match["workflow"],
        "businessFunction": match["businessFunction"],
        "problemStatement": clean[:400],
        "rootCauseHypothesis": root_cause_for(match["workflow"]),
        "desiredOutcome": desired_outcome,
        "decision": f"Which intervention best improves {desired_outcome} for {match['workflow'].replace('_', ' ')}?",
    }


QUESTION_BANK: List[Dict[str, Any]] = [
    {"id": "cycle_time", "question": "What is the current cycle time per item?", "why": "Baseline cycle time is required to quantify the impact of an intervention.", "factor": "Outcome evidence", "type": "choice", "options": ["Minutes", "Hours", "1–2 days", "3–5 days", "Weeks", "Not measured"], "required": True},
    {"id": "workflow_frequency", "question": "How often does this workflow run?", "why": "Frequency determines whether automation or redesign pays for itself.", "factor": "Outcome evidence", "type": "choice", "options": ["Daily", "Weekly", "Monthly", "Quarterly", "Continuously"], "required": True},
    {"id": "labor_cost", "question": "What is the loaded hourly cost of the people involved?", "why": "Without a labor cost, Compass cannot estimate dollar-denominated savings.", "factor": "Outcome evidence", "type": "choice", "options": ["<$20/hr", "$20–$40/hr", "$40–$60/hr", "$60–$100/hr", "$100+/hr"], "required": False},
    {"id": "people_involved", "question": "How many people are involved today?", "why": "Team size scales the time an intervention can return.", "factor": "Problem fit", "type": "choice", "options": ["1 person", "2–3 people", "4–10 people", "11–50 people", "50+ people"], "required": False},
    {"id": "exception_rate", "question": "How many exceptions or edge cases arise?", "why": "Exception rate decides how much of the workflow can be automated or standardized.", "factor": "Intervention suitability", "type": "choice", "options": ["Few (<5%)", "Some (5–10%)", "Many (10–30%)", "Highly variable (30%+)"], "required": False},
    {"id": "judgment_requirement", "question": "Does the work require judgment, or is it rule-based?", "why": "Rule-based work can be automated; judgment-heavy work needs human review.", "factor": "Intervention suitability", "type": "choice", "options": ["Fully rule-based", "Mostly rule-based", "Mixed", "Mostly judgment"], "required": False},
    {"id": "budget_range", "question": "What implementation budget is available?", "why": "Budget constrains which intervention families are feasible.", "factor": "Implementation evidence", "type": "choice", "options": ["Under $10K", "$10K–$50K", "$50K–$100K", "$100K–$250K", "$250K+"], "required": False},
    {"id": "implementation_timeline", "question": "What is your expected timeline?", "why": "Timeline filters out interventions that cannot deliver in time.", "factor": "Implementation evidence", "type": "choice", "options": ["1–2 months", "3–4 months", "5–6 months", "6–12 months", "Flexible"], "required": False},
    {"id": "business_risk", "question": "What is the risk of getting this wrong?", "why": "Risk shapes how much validation an intervention needs before commitment.", "factor": "Risk coverage", "type": "choice", "options": ["Low", "Medium", "High", "Critical"], "required": False},
    {"id": "process_stability", "question": "How stable is this process?", "why": "Unstable processes need redesign before automation.", "factor": "Risk coverage", "type": "choice", "options": ["Very stable", "Mostly stable", "Somewhat variable", "Highly variable"], "required": False},
]

INFERRED_PATTERNS: List[Dict[str, str]] = [
    {"id": "cycle_time", "match": r"\d+\s*(minutes|hours|days|weeks)"},
    {"id": "workflow_frequency", "match": r"daily|weekly|monthly|quarterly|per day|per week|per month"},
    {"id": "people_involved", "match": r"\d+\s*(people|fte|staff|employees|agents|analysts|reps)"},
    {"id": "exception_rate", "match": r"exception|edge case|error rate|error-prone|variable"},
    {"id": "budget_range", "match": r"budget|funding|\$\d|\b\d{2,4}k\b|capital"},
    {"id": "desired_outcome", "match": r".*"},
]


def infer_answers_from_text(text: str) -> Set[str]:
    found: Set[str] = set()
    for p in INFERRED_PATTERNS:
        if re.search(p["match"], text, re.IGNORECASE):
            found.add(p["id"])
    return found


def select_follow_ups(text: str, answers: Dict[str, str], engine_gaps: List[Dict[str, str]], max_questions: int = 5) -> List[Dict[str, Any]]:
    inferred = infer_answers_from_text(text)
    gap_titles = " ".join((g.get("title") or "").lower() for g in engine_gaps)
    has_volume_gap = "volume" in gap_titles or "handling time" in gap_titles
    has_labor_gap = "labor cost" in gap_titles or "loaded" in gap_titles

    priority: List[str] = []
    if has_volume_gap:
        priority += ["cycle_time", "workflow_frequency"]
    if has_labor_gap:
        priority.append("labor_cost")
    priority += [
        "cycle_time",
        "workflow_frequency",
        "people_involved",
        "exception_rate",
        "judgment_requirement",
        "budget_range",
        "implementation_timeline",
        "business_risk",
        "process_stability",
    ]

    outcome_inferred = infer_desired_outcome(text) != "efficiency" or bool(re.search(r"outcome|result|goal", text.lower()))

    result: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    if not outcome_inferred:
        q = {
            "id": "desired_outcome",
            "question": "What outcome matters most?",
            "why": "The decision is ranked around the outcome you are trying to improve.",
            "factor": "Goal alignment",
            "type": "choice",
            "options": ["Reduce cost", "Save time", "Improve quality", "Increase revenue", "Compliance", "Scale capacity"],
            "required": True,
        }
        result.append(q)
        seen.add(q["id"])

    by_id = {q["id"]: q for q in QUESTION_BANK}
    for qid in priority:
        if len(result) >= max_questions:
            break
        if qid in inferred or answers.get(qid) or qid in seen:
            continue
        q = by_id.get(qid)
        if q:
            result.append(q)
            seen.add(qid)
    return result[:max_questions]


def build_profile_from_analyze(normalization: Dict[str, str], answers: Dict[str, str]) -> Dict[str, Any]:
    current_tools = [answers.get("current_tools", "").strip()] if answers.get("current_tools", "").strip() else []
    return {
        "business_function": answers.get("business_function") or normalization["businessFunction"],
        "workflow": answers.get("workflow") or normalization["workflow"],
        "problem_statement": answers.get("problem_statement") or normalization["problemStatement"],
        "industry": answers.get("industry", ""),
        "company_size": answers.get("company_size", ""),
        "workflow_frequency": answers.get("workflow_frequency", ""),
        "people_involved": answers.get("people_involved", ""),
        "handoffs": answers.get("handoffs", ""),
        "current_tools": current_tools,
        "exception_rate": answers.get("exception_rate", ""),
        "budget_range": answers.get("budget_range", ""),
        "implementation_timeline": answers.get("implementation_timeline", ""),
        "business_risk": answers.get("business_risk", ""),
        "process_stability": answers.get("process_stability", ""),
        "previous_attempts": answers.get("previous_attempts", ""),
        "desired_outcome": answers.get("desired_outcome") or normalization["desiredOutcome"],
    }
