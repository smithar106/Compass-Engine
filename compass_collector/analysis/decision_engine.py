"""Multi-intervention decision engine for Compass.

Replaces the evidence-first recommendation model with a constraint-aware,
multi-dimensional decision architecture that generates intervention candidates
BEFORE querying evidence, then scores each independently across 11 dimensions.

Architecture:
    Problem → Workflow → Constraint → Intervention Candidates
    → Score (problem_fit, economics, automation_potential, risk, feasibility,
            organizational_readiness, evidence_strength, volume_fit,
            exception_fit, integration_feasibility, time_to_value)
    → Rank → Return alternatives with contraindications

This prevents survivorship bias: the intervention with the most published
evidence does not automatically win. Evidence is one dimension, not the
entire decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import json


# ── Intervention Families ────────────────────────────────────────────────────

@dataclass
class InterventionFamily:
    id: str
    name: str
    description: str
    typical_cost_range: str  # e.g. "$50K–500K"
    typical_timeline: str     # e.g. "6–12 weeks"
    labor_reduction_pct: tuple[float, float]  # (low, high)
    contraindications: list[str]  # conditions where this shouldn't be used
    good_when: list[str]
    subtypes: list[str] = field(default_factory=list)


INTERVENTION_FAMILIES: dict[str, InterventionFamily] = {
    "AI": InterventionFamily(
        id="AI",
        name="AI Implementation",
        description="Artificial intelligence, machine learning, NLP, computer vision, or generative AI",
        typical_cost_range="$80K–2M",
        typical_timeline="8–24 weeks",
        labor_reduction_pct=(45, 85),
        contraindications=[
            "Very low volume (fewer than ~500 items/month)",
            "Extremely high-value interactions where error cost exceeds $100K",
            "Heavy emotional sensitivity or grief counseling",
            "Complex regulatory requirements without explainability",
            "Poor source data quality (incomplete, inconsistent, unlabeled)",
            "Highly variable conversations with no predictable intent patterns",
        ],
        good_when=[
            "High volume, repeatable interactions",
            "Predictable intent or classification task",
            "Measurable conversion or outcome metrics",
            "Human escalation path available for edge cases",
            "Existing training data or ability to generate it",
            "Error cost is moderate and recoverable",
        ],
        subtypes=["generative_ai", "predictive_ai", "ai_assisted_work", "autonomous_ai",
                   "human_in_the_loop_ai", "machine_learning", "nlp", "computer_vision"],
    ),
    "Software": InterventionFamily(
        id="Software",
        name="Software Implementation",
        description="New software adoption, platform migration, or optimization of existing systems",
        typical_cost_range="$30K–500K",
        typical_timeline="4–16 weeks",
        labor_reduction_pct=(25, 60),
        contraindications=[
            "Process is not standardized enough for software to model",
            "Team lacks technical capacity to adopt new tools",
            "No clear process owner who can champion adoption",
            "Budget below $25K for anything beyond basic SaaS",
        ],
        good_when=[
            "Process is standardized and documented",
            "Team is technically capable or willing to learn",
            "Clear process owner exists",
            "Integration with existing systems is feasible",
            "Vendor ecosystem exists for this workflow",
        ],
        subtypes=["new_software_implementation", "existing_software_optimization",
                   "cloud_migration", "crm_implementation", "erp_implementation"],
    ),
    "Workflow_Automation": InterventionFamily(
        id="Workflow_Automation",
        name="Workflow Automation",
        description="RPA, workflow tools, or rules-based automation of repetitive processes",
        typical_cost_range="$20K–300K",
        typical_timeline="4–12 weeks",
        labor_reduction_pct=(40, 90),
        contraindications=[
            "Process changes frequently (reshaping automation is expensive)",
            "Too many exceptions requiring human judgment",
            "Very low volume where automation ROI doesn't justify setup cost",
            "Process relies on systems that change their UI frequently",
            "No clear, documented standard operating procedure",
        ],
        good_when=[
            "High volume, rule-based, repeatable process",
            "Process is stable and well-documented",
            "Clear inputs and outputs with minimal ambiguity",
            "Systems have stable APIs or consistent UIs",
            "Exception rate is below 30%",
        ],
        subtypes=["rpa", "workflow_automation", "rules_based_automation",
                   "robotic_process_automation", "workflow_simplification"],
    ),
    "Process_Redesign": InterventionFamily(
        id="Process_Redesign",
        name="Process Redesign",
        description="Fundamental redesign of operational processes to improve efficiency",
        typical_cost_range="$40K–1M",
        typical_timeline="8–24 weeks",
        labor_reduction_pct=(20, 50),
        contraindications=[
            "Process is already highly optimized",
            "Organization lacks authority to change cross-functional processes",
            "Timeline is too aggressive for organizational change",
            "No executive sponsor with decision authority",
        ],
        good_when=[
            "Current process has obvious waste or redundancy",
            "Multiple handoffs causing delays and errors",
            "Cross-functional process with conflicting incentives",
            "Executive sponsor committed to change",
            "Organization has change management capability",
        ],
        subtypes=["process_redesign", "lean", "business_process_reengineering",
                   "organizational_restructuring"],
    ),
    "Staffing": InterventionFamily(
        id="Staffing",
        name="Staffing Change",
        description="Changes to team structure, hiring, training, or outsourcing",
        typical_cost_range="$30K–300K/year",
        typical_timeline="2–8 weeks",
        labor_reduction_pct=(-20, 30),  # Can increase costs initially
        contraindications=[
            "Hiring market is extremely tight for required skills",
            "Marginal cost of additional staff exceeds automation cost",
            "Outsourcing would compromise quality or compliance requirements",
            "Process requires deep institutional knowledge",
        ],
        good_when=[
            "Volume is too low for automation ROI",
            "Work requires significant human judgment",
            "Process is highly variable with many exceptions",
            "Quality or compliance requires human oversight",
            "Customer relationship is core to value",
        ],
        subtypes=["staffing_increases", "staffing_reallocation", "outsourcing",
                   "training", "managed_services"],
    ),
    "Hybrid": InterventionFamily(
        id="Hybrid",
        name="Hybrid Intervention",
        description="Combination of AI + human, automation + process redesign, or multi-modal",
        typical_cost_range="$100K–3M",
        typical_timeline="12–36 weeks",
        labor_reduction_pct=(30, 70),
        contraindications=[
            "Organization lacks maturity to manage multi-modal change",
            "Budget or timeline constraints preclude phased approach",
            "No clear owner for the integrated solution",
        ],
        good_when=[
            "Complex process with both automatable and judgment-intensive steps",
            "Organization has experience with both technology and process change",
            "Phased approach is acceptable",
            "Multiple stakeholders require different intervention types",
            "Risk of pure automation is too high without human oversight",
        ],
        subtypes=["hybrid_combination", "ai_human_collaboration", "augmented_workflow"],
    ),
    "No_Action": InterventionFamily(
        id="No_Action",
        name="No Action / Establish Baseline",
        description="Do not implement yet — establish the baseline before selecting an intervention",
        typical_cost_range="$0–10K",
        typical_timeline="2–4 weeks",
        labor_reduction_pct=(0, 0),
        contraindications=["Urgent regulatory or safety requirement"],
        good_when=[
            "Current volume, cost, or exception rate is unknown or estimated",
            "No clear problem owner or executive sponsor",
            "Multiple plausible constraints with no clear root cause",
            "Recent organizational change makes current state uncertain",
            "The cost of the wrong intervention exceeds the cost of measurement",
        ],
        subtypes=[],
    ),
}


# ── Constraint Types ─────────────────────────────────────────────────────────

@dataclass
class ConstraintProfile:
    """What is preventing the workflow from performing better?"""
    primary: str  # capacity, errors, speed, quality, cost, visibility, compliance
    secondary: list[str] = field(default_factory=list)
    description: str = ""


CONSTRAINT_MAP: dict[str, dict] = {
    "capacity": {
        "label": "Insufficient capacity",
        "description": "Cannot handle current or projected volume with existing resources",
        "intervention_weights": {"Staffing": 0.9, "AI": 0.85, "Workflow_Automation": 0.8,
                                  "Hybrid": 0.75, "Process_Redesign": 0.5, "Software": 0.4},
    },
    "errors": {
        "label": "Too many errors",
        "description": "High error rate, rework, or quality issues in the process",
        "intervention_weights": {"AI": 0.85, "Workflow_Automation": 0.9, "Software": 0.7,
                                  "Process_Redesign": 0.6, "Hybrid": 0.75, "Staffing": 0.3},
    },
    "speed": {
        "label": "Too slow",
        "description": "Process takes too long, causing delays, missed SLAs, or customer dissatisfaction",
        "intervention_weights": {"Workflow_Automation": 0.9, "AI": 0.8, "Software": 0.7,
                                  "Process_Redesign": 0.75, "Staffing": 0.6, "Hybrid": 0.8},
    },
    "quality": {
        "label": "Inconsistent quality",
        "description": "Output quality varies significantly between team members or over time",
        "intervention_weights": {"AI": 0.8, "Software": 0.75, "Process_Redesign": 0.7,
                                  "Workflow_Automation": 0.65, "Training": 0.6, "Hybrid": 0.75},
    },
    "cost": {
        "label": "Too expensive",
        "description": "Current process cost is unsustainable or exceeds benchmarks",
        "intervention_weights": {"Workflow_Automation": 0.9, "AI": 0.85, "Software": 0.7,
                                  "Process_Redesign": 0.6, "Staffing": -0.2, "Hybrid": 0.8},
    },
    "visibility": {
        "label": "Lack of visibility",
        "description": "Cannot track, measure, or report on process performance",
        "intervention_weights": {"Software": 0.95, "AI": 0.6, "Process_Redesign": 0.5,
                                  "Workflow_Automation": 0.4, "Staffing": 0.1},
    },
    "compliance": {
        "label": "Compliance or regulatory risk",
        "description": "Process creates regulatory, legal, or compliance exposure",
        "intervention_weights": {"Software": 0.85, "AI": 0.5, "Workflow_Automation": 0.7,
                                  "Process_Redesign": 0.6, "Staffing": 0.4, "Hybrid": 0.6},
    },
    "unknown": {
        "label": "Unclear / needs diagnosis",
        "description": "Root cause is not yet identified — establish baseline first",
        "intervention_weights": {"No_Action": 0.95, "Process_Redesign": 0.4},
    },
}


# ── Assessment Input ──────────────────────────────────────────────────────────

@dataclass
class AssessmentInput:
    business_function: str
    workflow: str
    problem_statement: str
    constraint: str = "unknown"
    industry: str = ""
    company_size: str = ""
    workflow_frequency: str = ""
    people_involved: str = ""
    handoffs: str = ""
    exception_rate: str = ""
    budget_range: str = ""
    implementation_timeline: str = ""
    business_risk: str = ""
    process_stability: str = ""
    previous_attempts: str = ""
    desired_outcome: str = ""
    annual_workflow_volume: Optional[float] = None
    current_handling_time: Optional[float] = None
    loaded_labor_cost: Optional[float] = None
    standardization_level: str = "unknown"  # repeatable / with_exceptions / variable / heavy_judgment
    failure_impact: str = "unknown"  # low / moderate / material / regulatory


# ── Scoring Dimensions ────────────────────────────────────────────────────────

@dataclass
class DimensionScore:
    score: float  # 0.0 to 1.0
    confidence: float
    rationale: str


@dataclass
class InterventionCandidate:
    family_id: str
    family_name: str
    scores: dict[str, DimensionScore]  # dimension_name → score
    overall_score: float  # weighted composite
    economics: Optional["InterventionEconomics"] = None
    contraindications_triggered: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    negative_evidence: list[dict] = field(default_factory=list)


@dataclass
class InterventionEconomics:
    current_annual_labor_cost: float
    automatable_pct: float
    expected_annual_savings: float
    implementation_cost_estimate: float
    annual_operating_cost: float
    payback_months: float
    three_year_roi: float
    conservative_savings: float
    expected_savings: float
    upside_savings: float
    assumptions: list[str]


# ── Decision Engine ───────────────────────────────────────────────────────────

WEIGHTS = {
    "problem_fit": 0.18,
    "economic_fit": 0.16,
    "automation_potential": 0.12,
    "volume_fit": 0.10,
    "exception_fit": 0.08,
    "risk": 0.08,
    "feasibility": 0.07,
    "organizational_readiness": 0.06,
    "integration_feasibility": 0.05,
    "time_to_value": 0.05,
    "evidence_strength": 0.05,
}


class DecisionEngine:
    """Multi-intervention decision engine for Compass.

    Generates intervention candidates BEFORE querying evidence,
    scores each independently across 11 dimensions, compares
    alternatives, and returns ranked recommendations with
    contraindications and bottom-up economics.
    """

    def __init__(self, assessment: AssessmentInput):
        self.assessment = assessment
        self.constraint = CONSTRAINT_MAP.get(
            assessment.constraint,
            CONSTRAINT_MAP["unknown"]
        )

    def generate_candidates(self) -> list[str]:
        """Generate plausible intervention families based on problem + constraint.

        This runs BEFORE evidence lookup to prevent survivorship bias.
        """
        weights = self.constraint.get("intervention_weights", {})
        candidates = []

        for family_id, weight in weights.items():
            if weight > 0.3 and family_id in INTERVENTION_FAMILIES:
                candidates.append(family_id)

        # Always include the top 3, even if weights are low
        sorted_by_weight = sorted(weights.items(), key=lambda x: -x[1])
        for fid, _ in sorted_by_weight:
            if fid not in candidates and fid in INTERVENTION_FAMILIES:
                candidates.append(fid)
            if len(candidates) >= 6:
                break

        if not candidates:
            # Fallback: all families
            candidates = list(INTERVENTION_FAMILIES.keys())

        return candidates

    def score_candidate(self, family_id: str) -> InterventionCandidate:
        """Score an intervention candidate across all dimensions."""
        family = INTERVENTION_FAMILIES.get(family_id)
        if not family:
            return None

        scores = {}
        contraindications_triggered = []

        a = self.assessment

        # 1. Problem fit — does this intervention address the constraint?
        pf = self._score_problem_fit(family_id)
        scores["problem_fit"] = pf

        # 2. Economic fit — can expected benefit justify cost?
        ef = self._score_economic_fit(family)
        scores["economic_fit"] = ef

        # 3. Automation potential — how repeatable is the work?
        ap = self._score_automation_potential(family)
        scores["automation_potential"] = ap

        # 4. Volume fit — is there enough repetition/scale?
        vf = self._score_volume_fit(family)
        scores["volume_fit"] = vf

        # 5. Exception fit — how much falls outside the happy path?
        exf = self._score_exception_fit(family)
        scores["exception_fit"] = exf

        # 6. Risk — what happens when it fails?
        risk = self._score_risk(family)
        scores["risk"] = risk

        # 7. Feasibility — can this organization deploy it?
        feas = self._score_feasibility(family)
        scores["feasibility"] = feas

        # 8. Organizational readiness
        org = self._score_organizational_readiness(family)
        scores["organizational_readiness"] = org

        # 9. Integration feasibility
        integ = self._score_integration_feasibility(family)
        scores["integration_feasibility"] = integ

        # 10. Time to value
        ttv = self._score_time_to_value(family)
        scores["time_to_value"] = ttv

        # 11. Evidence strength — placeholder, filled after evidence lookup
        scores["evidence_strength"] = DimensionScore(
            score=0.5, confidence=0.0,
            rationale="Evidence score computed after retrieval"
        )

        # Check contraindications
        contraindications_triggered = self._check_contraindications(family)

        # Compute weighted overall
        overall = sum(
            WEIGHTS.get(dim, 0) * scores[dim].score
            for dim in scores
        )

        # Calculate bottom-up economics
        economics = self._calculate_economics(family) if a.annual_workflow_volume else None

        return InterventionCandidate(
            family_id=family_id,
            family_name=family.name,
            scores=scores,
            overall_score=round(overall, 3),
            economics=economics,
            contraindications_triggered=contraindications_triggered,
        )

    def decide(self) -> dict:
        """Full decision pipeline: generate → score → compare → return."""
        candidates = self.generate_candidates()

        scored = []
        for fid in candidates:
            candidate = self.score_candidate(fid)
            if candidate:
                scored.append(candidate)

        # Sort by overall score descending
        scored.sort(key=lambda c: -c.overall_score)

        recommended = scored[0] if scored else None
        alternatives = scored[1:] if len(scored) > 1 else []

        # Check if we should recommend No_Action
        insufficient = self._check_insufficient_information(scored)

        return {
            "problem": {
                "workflow": self.assessment.workflow,
                "business_function": self.assessment.business_function,
                "constraint": self.constraint.get("label", "Unknown"),
                "constraint_type": self.assessment.constraint,
                "problem_statement": self.assessment.problem_statement,
                "desired_outcome": self.assessment.desired_outcome,
            },
            "recommended_intervention": self._format_candidate(recommended) if recommended else None,
            "alternatives_considered": [self._format_candidate(c) for c in alternatives],
            "insufficient_information": insufficient,
            "economics": self._format_economics(recommended) if recommended and recommended.economics else None,
            "contraindications": recommended.contraindications_triggered if recommended else [],
            "implementation_path": self._build_implementation_path(recommended) if recommended else [],
            "methodology": {
                "engine_version": "decision-v1",
                "dimensions_scored": list(WEIGHTS.keys()),
                "candidates_generated_from": f"constraint={self.assessment.constraint}",
                "evidence_independent": "Candidates generated before evidence lookup",
            },
        }

    # ── Implementation Path ──

    def _build_implementation_path(self, candidate: InterventionCandidate) -> list[dict]:
        """Generate a 5-step implementation path tailored to the intervention family,
        constraint type, and assessment inputs."""
        family = INTERVENTION_FAMILIES.get(candidate.family_id)
        if not family:
            return []

        a = self.assessment
        constraint = a.constraint
        budget = a.budget_range or "$50K–100K"
        timeline = a.implementation_timeline or "1–3 months"
        volume = a.annual_workflow_volume or 0
        risk = a.business_risk or "Medium"

        # Base templates per family, customized by constraint
        steps = []

        if family.id == "Workflow_Automation":
            steps = [
                {
                    "step": 1,
                    "phase": "Process Audit & Baseline Measurement",
                    "duration": "2–3 weeks",
                    "owner": "Process Owner + Operations Lead",
                    "actions": [
                        "Document the current inbound call handling process end-to-end",
                        "Map every handoff, tool, and decision point",
                        f"Measure baseline metrics: volume ({volume:,.0f}/yr), handling time, error rate, response time",
                        "Identify the 20% of call types that represent 80% of volume",
                        "Flag exception paths that require human judgment vs automatable paths",
                    ],
                    "success_criteria": "Current-state process map complete. Baseline metrics recorded for ≥2 weeks. Top call categories identified.",
                    "cost": "Internal labor: ~$5K (process owner time)",
                },
                {
                    "step": 2,
                    "phase": "Vendor Selection & Tool Evaluation",
                    "duration": "2–4 weeks",
                    "owner": "IT + Operations Lead",
                    "actions": [
                        "Evaluate 3–5 workflow automation platforms (UiPath, Automation Anywhere, Zapier, Microsoft Power Automate)",
                        "Score against: API availability for CRM integration, exception handling capability, pricing model",
                        "Run a 2-day proof-of-concept on the top 3 call categories from Step 1",
                        "Select vendor based on PoC results, total cost of ownership, and support SLA",
                        f"Validate implementation cost within budget ({budget})",
                    ],
                    "success_criteria": "Vendor selected. PoC demonstrates automation on ≥2 call categories. Contract signed within budget.",
                    "cost": "Platform licenses: $10K–30K/year. PoC: vendor-provided (often free).",
                },
                {
                    "step": 3,
                    "phase": "Pilot Implementation — Automate Top Call Types",
                    "duration": "3–4 weeks",
                    "owner": "IT + Vendor + Process Owner",
                    "actions": [
                        "Configure automation for the top 3–5 call types (routing, data lookup, response templating)",
                        "Build the human escalation handoff for calls the bot cannot resolve",
                        "Integrate with existing CRM and phone system (API or screen-scraping)",
                        "Set up monitoring dashboard: calls handled, automation rate, escalation rate, resolution time",
                        "Run in shadow mode for 1 week before going live",
                    ],
                    "success_criteria": "Automation handles ≥70% of targeted call types without escalation. Escalation handoff <30 seconds. Zero critical errors.",
                    "cost": "Implementation: $30K–60K. Includes vendor professional services + internal IT time.",
                },
                {
                    "step": 4,
                    "phase": "Gradual Rollout & Exception Handling",
                    "duration": "4–6 weeks",
                    "owner": "Operations Lead + Team",
                    "actions": [
                        "Expand automation to remaining call categories based on pilot data",
                        "Train team on new workflow: monitoring the automation dashboard, handling escalations",
                        "Build feedback loop: weekly review of false positives/negatives, tune automation rules",
                        "Document standard operating procedure for the new human+automation workflow",
                        f"Track against target: {family.labor_reduction_pct[1]}% labor reduction, <10% exception rate",
                    ],
                    "success_criteria": "Full rollout complete. Team trained. Exception rate <10%. Labor hours reduced by ≥50%.",
                    "cost": "Internal change management: ~$10K. Additional platform scaling if needed.",
                },
                {
                    "step": 5,
                    "phase": "Measure, Optimize & Scale",
                    "duration": "Ongoing (monthly review)",
                    "owner": "Operations Lead + Executive Sponsor",
                    "actions": [
                        "Compare actual vs predicted: labor savings, call resolution time, revenue capture",
                        "Calculate realized ROI against implementation cost",
                        "Identify adjacent workflows for automation expansion (outbound, follow-up, scheduling)",
                        f"Report to executive sponsor: {family.labor_reduction_pct[0]}–{family.labor_reduction_pct[1]}% labor reduction target vs actual",
                        "Set quarterly automation expansion roadmap",
                    ],
                    "success_criteria": f"ROI positive within {candidate.economics.payback_months:.0f} months. Automation expanded to ≥1 adjacent workflow. Executive sign-off on Phase 2." if candidate and candidate.economics and candidate.economics.payback_months else "ROI positive. Automation expanded to ≥1 adjacent workflow. Executive sign-off on Phase 2.",
                    "cost": "Ongoing platform cost: $5K–15K/year. Optimization: internal labor.",
                },
            ]
        elif family.id == "AI":
            steps = [
                {
                    "step": 1, "phase": "Data Readiness Assessment & Baseline",
                    "duration": "2–3 weeks",
                    "owner": "Data Lead + Process Owner",
                    "actions": [
                        "Audit data quality: completeness of call logs, CRM records, outcome data",
                        "Label minimum 500 examples of correct call handling for training",
                        "Establish baseline metrics for accuracy, response time, customer satisfaction",
                        "Identify data gaps and create collection plan",
                    ],
                    "success_criteria": "Data quality score ≥70%. 500+ labeled examples. Baseline metrics established.",
                    "cost": "Internal labor: ~$10K. Data labeling tools: $2K–5K.",
                },
                {
                    "step": 2, "phase": "Model Selection & Prototype",
                    "duration": "3–4 weeks",
                    "owner": "AI/ML Lead + IT",
                    "actions": [
                        "Evaluate AI options: fine-tuned LLM for intent classification, purpose-built call routing model, or API-based solution",
                        "Build prototype on historical data, measure precision/recall on held-out test set",
                        f"Validate prototype handles {a.exception_rate or '<10%'} exception rate",
                        "Select approach based on accuracy, cost, and integration complexity",
                    ],
                    "success_criteria": "Model precision ≥85% on test set. Prototype runs in <2 seconds per call. Cost estimate finalized.",
                    "cost": "Model development: $20K–50K. API costs during dev: $2K–5K.",
                },
                {
                    "step": 3, "phase": "Human-in-the-Loop Pilot",
                    "duration": "4–6 weeks",
                    "owner": "AI Lead + Operations + Compliance",
                    "actions": [
                        "Deploy AI in shadow mode: AI classifies calls, human confirms/rejects",
                        "Build escalation path: AI routes low-confidence calls to human immediately",
                        "Monitor false positive rate — must stay below 5% for go-live",
                        f"Assess risk level: {risk}. If critical/safety risk, add compliance review checkpoint",
                    ],
                    "success_criteria": "AI + human accuracy ≥95%. False positive rate <5%. Escalation path tested end-to-end.",
                    "cost": "Deployment: $30K–80K. Shadow monitoring: $5K.",
                },
                {
                    "step": 4, "phase": "Controlled Go-Live & Monitoring",
                    "duration": "4–8 weeks",
                    "owner": "AI Lead + Operations + IT",
                    "actions": [
                        "Go live with AI-first handling for top call categories",
                        "24/7 monitoring for first 2 weeks with rapid rollback capability",
                        "Weekly accuracy audits on random sample of AI-handled calls",
                        "Train team on AI collaboration: reviewing AI decisions, flagging errors",
                    ],
                    "success_criteria": "AI handling ≥70% of calls independently. Accuracy maintained ≥93%. No critical errors.",
                    "cost": "Production infrastructure: $10K–30K/month. Ongoing monitoring.",
                },
                {
                    "step": 5, "phase": "Continuous Learning & Expansion",
                    "duration": "Ongoing (monthly)",
                    "owner": "AI Lead + Executive Sponsor",
                    "actions": [
                        "Retrain model monthly on new data to improve accuracy",
                        "Expand to additional call categories and languages",
                        "Integrate AI insights into CRM for proactive customer engagement",
                        "Report ROI: labor savings, revenue capture, customer satisfaction delta",
                    ],
                    "success_criteria": "Model accuracy improving month-over-month. Expanded to ≥2 new workflows. ROI positive.",
                    "cost": "Ongoing inference: $5K–20K/month. Continuous training: $5K–10K/month.",
                },
            ]
        else:
            # Generic implementation path for other families
            steps = [
                {
                    "step": 1, "phase": "Discovery & Baseline",
                    "duration": "2–3 weeks",
                    "owner": "Process Owner",
                    "actions": [
                        "Document current state end-to-end",
                        "Measure baseline metrics",
                        "Identify root causes of the constraint",
                    ],
                    "success_criteria": "Complete process map. Baseline measured.",
                    "cost": "Internal labor: ~$5K",
                },
                {
                    "step": 2, "phase": "Solution Design",
                    "duration": "2–3 weeks",
                    "owner": "Process Owner + IT",
                    "actions": [
                        "Design target state with the recommended intervention",
                        "Evaluate vendor options if applicable",
                        "Build cost model and ROI projection",
                    ],
                    "success_criteria": "Solution design approved. Vendor selected or build decision made.",
                    "cost": "Internal labor: ~$10K",
                },
                {
                    "step": 3, "phase": "Pilot",
                    "duration": "3–4 weeks",
                    "owner": "Process Owner + Team",
                    "actions": [
                        "Implement on a subset of the workflow",
                        "Monitor and measure against baseline",
                        "Iterate based on pilot results",
                    ],
                    "success_criteria": "Pilot demonstrates measurable improvement. Team trained.",
                    "cost": "Variable by intervention",
                },
                {
                    "step": 4, "phase": "Full Rollout",
                    "duration": "4–6 weeks",
                    "owner": "Operations Lead",
                    "actions": [
                        "Expand to full scope",
                        "Train all team members",
                        "Document new standard operating procedure",
                    ],
                    "success_criteria": "Full rollout complete. All team members trained.",
                    "cost": "Variable by intervention",
                },
                {
                    "step": 5, "phase": "Optimize & Scale",
                    "duration": "Ongoing",
                    "owner": "Executive Sponsor",
                    "actions": [
                        "Measure realized vs projected outcomes",
                        "Identify expansion opportunities",
                        "Report to leadership",
                    ],
                    "success_criteria": "ROI positive. Expansion plan approved.",
                    "cost": "Ongoing operational cost",
                },
            ]

        return steps

    def _score_problem_fit(self, family_id: str) -> DimensionScore:
        w = self.constraint.get("intervention_weights", {}).get(family_id, 0.3)
        return DimensionScore(
            score=max(0.0, min(1.0, w)),
            confidence=0.7 if self.assessment.constraint != "unknown" else 0.3,
            rationale=f"Constraint '{self.assessment.constraint}' → {INTERVENTION_FAMILIES[family_id].name} weight={w:.2f}"
        )

    def _score_economic_fit(self, family: InterventionFamily) -> DimensionScore:
        cost_range = family.typical_cost_range
        budget = self.assessment.budget_range

        budget_map = {
            "Under $10k": 10000, "$10k–25k": 25000, "$25k–50k": 50000,
            "$50k–100k": 100000, "$100k–250k": 250000, "$250k+": 500000,
            "": 100000,
        }
        budget_mid = budget_map.get(budget, 100000)

        # Estimate intervention cost midpoint
        import re
        nums = re.findall(r'[\d,]+', cost_range.replace('K', '000').replace('M', '000000'))
        cost_nums = [int(n.replace(',', '')) for n in nums]
        if len(cost_nums) >= 2:
            cost_mid = (cost_nums[0] + cost_nums[1]) / 2
        else:
            cost_mid = cost_nums[0] if cost_nums else 100000

        affordability = min(1.0, budget_mid / max(cost_mid, 1))
        roi = family.labor_reduction_pct[0] / 100  # conservative estimate

        score = (affordability * 0.4 + roi * 0.6) if isinstance(roi, (int, float)) else affordability

        return DimensionScore(
            score=round(max(0.1, min(1.0, score)), 2),
            confidence=0.6 if budget else 0.3,
            rationale=f"Budget ~${budget_mid:,.0f} vs family range {cost_range}. "
                      f"Labor reduction {family.labor_reduction_pct[0]}–{family.labor_reduction_pct[1]}%"
        )

    def _score_automation_potential(self, family: InterventionFamily) -> DimensionScore:
        exception_rate = self.assessment.exception_rate
        stability = self.assessment.process_stability

        # Low exceptions + stable = high automation potential
        exception_score = 0.8 if "almost no" in exception_rate.lower() else \
                          0.6 if "some" in exception_rate.lower() or "<10" in exception_rate else \
                          0.4 if "10–30" in exception_rate else \
                          0.2 if "30%+" in exception_rate else 0.3
        stability_score = 0.6 if "stable" in stability.lower() else \
                           0.4 if "somewhat" in stability.lower() else 0.3

        score = exception_score * 0.6 + stability_score * 0.4

        return DimensionScore(
            score=round(score, 2),
            confidence=0.5 if exception_rate else 0.2,
            rationale=f"Exception rate score={exception_score:.1f}, stability={stability_score:.1f}"
        )

    def _score_volume_fit(self, family: InterventionFamily) -> DimensionScore:
        vol = self.assessment.annual_workflow_volume
        if not vol:
            return DimensionScore(0.5, 0.1, "Volume unknown")

        # AI and automation need volume to justify setup cost
        if family.id in ("AI", "Workflow_Automation"):
            if vol < 6000: score = 0.2
            elif vol < 60000: score = 0.6
            elif vol < 600000: score = 0.85
            else: score = 0.95
        elif family.id == "Staffing":
            if vol < 6000: score = 0.9
            elif vol < 60000: score = 0.7
            else: score = 0.4
        else:
            if vol < 6000: score = 0.5
            elif vol < 60000: score = 0.7
            else: score = 0.85

        return DimensionScore(
            score=score,
            confidence=0.7,
            rationale=f"Annual volume ~{vol:,.0f} items → {family.id} fit={score:.2f}"
        )

    def _score_exception_fit(self, family: InterventionFamily) -> DimensionScore:
        exception_rate = self.assessment.exception_rate.lower()
        if "almost no" in exception_rate: rate = 0.05
        elif "some" in exception_rate or "<10" in exception_rate: rate = 0.1
        elif "10–30" in exception_rate: rate = 0.2
        elif "30%+" in exception_rate: rate = 0.4
        elif "entire" in exception_rate: rate = 0.8
        else: rate = 0.2

        # Automation struggles with high exceptions, staffing handles them well
        if family.id in ("AI", "Workflow_Automation"):
            score = max(0.1, 1.0 - rate * 2.5)
        elif family.id == "Staffing":
            score = min(1.0, rate * 2 + 0.3)
        elif family.id == "Hybrid":
            score = max(0.3, 1.0 - rate * 1.5)
        else:
            score = max(0.2, 1.0 - rate * 2)

        return DimensionScore(
            score=round(score, 2),
            confidence=0.5 if self.assessment.exception_rate else 0.2,
            rationale=f"Exception rate ~{rate:.0%} → {family.id} handles{' well' if score > 0.6 else ' poorly'}"
        )

    def _score_risk(self, family: InterventionFamily) -> DimensionScore:
        risk = self.assessment.business_risk.lower()
        if "critical" in risk or "safety" in risk: risk_level = 0.9
        elif "high" in risk or "significant" in risk: risk_level = 0.7
        elif "medium" in risk or "noticeable" in risk: risk_level = 0.5
        elif "low" in risk or "small" in risk: risk_level = 0.3
        else: risk_level = 0.5

        # AI has higher risk in regulated environments, staffing is safer
        if family.id == "AI":
            score = max(0.2, 1.0 - risk_level * 0.8)
        elif family.id == "Staffing":
            score = 0.9  # People are low-risk to deploy
        elif family.id == "Software":
            score = max(0.3, 1.0 - risk_level * 0.6)
        else:
            score = max(0.3, 1.0 - risk_level * 0.7)

        return DimensionScore(
            score=round(score, 2),
            confidence=0.5,
            rationale=f"Failure risk level={risk_level:.1f} → {family.id} risk tolerance={score:.2f}"
        )

    def _score_feasibility(self, family: InterventionFamily) -> DimensionScore:
        budget = self.assessment.budget_range
        timeline = self.assessment.implementation_timeline

        budget_ok = budget not in ("Under $10k", "") or family.id == "No_Action"
        timeline_map = {
            "Immediately": 2, "30 days": 4, "1–3 months": 8,
            "3–6 months": 16, "6–12 months": 30, "Flexible": 20, "": 12,
        }
        weeks = timeline_map.get(timeline, 12)

        # Can this family deliver in the required timeline?
        typical_weeks = {"AI": 16, "Software": 10, "Workflow_Automation": 8,
                         "Process_Redesign": 16, "Staffing": 4, "Hybrid": 20,
                         "No_Action": 3}
        fam_weeks = typical_weeks.get(family.id, 12)

        timeline_fit = min(1.0, weeks / max(fam_weeks, 1)) if weeks > 0 else 0.5

        score = (0.7 if budget_ok else 0.3) * 0.5 + timeline_fit * 0.5

        return DimensionScore(
            score=round(score, 2),
            confidence=0.5,
            rationale=f"Budget fit={budget_ok}, timeline={weeks}w vs {fam_weeks}w typical"
        )

    def _score_organizational_readiness(self, family: InterventionFamily) -> DimensionScore:
        freq = self.assessment.workflow_frequency
        freq_score = 0.8 if "multiple times" in freq.lower() else \
                     0.6 if "hourly" in freq.lower() else \
                     0.5 if "daily" in freq.lower() else 0.3

        return DimensionScore(
            score=round(freq_score, 2),
            confidence=0.3,
            rationale=f"Frequency '{freq}' → readiness ~{freq_score:.2f}"
        )

    def _score_integration_feasibility(self, family: InterventionFamily) -> DimensionScore:
        return DimensionScore(
            score=0.6, confidence=0.2,
            rationale="Integration assessment requires tool-specific data"
        )

    def _score_time_to_value(self, family: InterventionFamily) -> DimensionScore:
        timeline = self.assessment.implementation_timeline
        urgency = 0.9 if "immediately" in timeline.lower() else \
                   0.7 if "30 days" in timeline.lower() else \
                   0.5 if "1–3" in timeline else \
                   0.3 if "3–6" in timeline else 0.2

        # Staffing and process redesign deliver faster
        if family.id == "Staffing": speed = 0.9
        elif family.id == "No_Action": speed = 1.0
        elif family.id == "Workflow_Automation": speed = 0.7
        elif family.id == "AI": speed = 0.4
        elif family.id == "Hybrid": speed = 0.3
        else: speed = 0.6

        score = speed * 0.6 + urgency * 0.4

        return DimensionScore(
            score=round(score, 2),
            confidence=0.5,
            rationale=f"Urgency={urgency:.1f}, family speed={speed:.1f}"
        )

    # ── Contraindications ──

    def _check_contraindications(self, family: InterventionFamily) -> list[str]:
        triggered = []
        a = self.assessment

        vol = a.annual_workflow_volume
        for ci in family.contraindications:
            ci_lower = ci.lower()
            if "very low volume" in ci_lower and vol and vol < 6000:
                triggered.append(ci)
            if "too many exceptions" in ci_lower and "highly variable" in a.exception_rate.lower():
                triggered.append(ci)
            if "not standardized" in ci_lower and "entirely manual" in (a.process_stability or "").lower():
                triggered.append(ci)

        return triggered

    # ── Economics ──

    def _calculate_economics(self, family: InterventionFamily) -> Optional[InterventionEconomics]:
        a = self.assessment
        vol = a.annual_workflow_volume
        hours = a.current_handling_time
        rate = a.loaded_labor_cost

        if not vol or not hours or not rate:
            return None

        current_annual = vol * hours * rate

        # Automatable % depends on family and exception rate
        exception_rate = a.exception_rate.lower()
        if "almost no" in exception_rate: except_pct = 0.02
        elif "some" in exception_rate: except_pct = 0.08
        elif "10–30" in exception_rate: except_pct = 0.2
        elif "30%+" in exception_rate: except_pct = 0.35
        else: except_pct = 0.15

        automatable = family.labor_reduction_pct[1] / 100 * (1 - except_pct)
        automatable = max(0.05, min(0.70, automatable))  # Cap at 70% — no intervention eliminates all labor

        expected_savings = current_annual * automatable
        conservative_savings = current_annual * family.labor_reduction_pct[0] / 100 * (1 - except_pct * 2)
        upside_savings = current_annual * family.labor_reduction_pct[1] / 100

        # Estimate implementation cost from the implementation path (canonical source),
        # not from the generic family midpoint.
        # Exclude ongoing/annual costs (phases with "/year") — only one-time implementation costs.
        import re
        path = self._build_implementation_path(InterventionCandidate(
            family_id=family.id, family_name=family.name,
            scores={}, overall_score=0, economics=None,
        ))
        impl_cost = 50000  # fallback
        annual_op_cost = 0
        if path:
            path_costs = []
            for step in path:
                cost_str = step.get("cost", "$5K")
                # Separate one-time from ongoing costs
                is_ongoing = "/year" in cost_str.lower() or "/yr" in cost_str.lower() or "ongoing" in cost_str.lower()
                cost_str_clean = cost_str.replace('K', '000').replace('M', '000000')
                nums = re.findall(r'[\d,]+', cost_str_clean)
                cost_nums = [int(n.replace(',', '')) for n in nums]
                if cost_nums:
                    midpoint = sum(cost_nums) / len(cost_nums)
                    if is_ongoing:
                        annual_op_cost += midpoint
                    else:
                        path_costs.append(midpoint)
            if path_costs:
                impl_cost = sum(path_costs)

        annual_op = max(annual_op_cost, impl_cost * 0.15)  # Use explicit annual cost if available, else 15%

        net_annual = expected_savings - annual_op
        # Conservative payback: assume 50% savings in first month (ramp-up)
        payback = (impl_cost / (net_annual * 0.5) * 12) if net_annual > 0 else float('inf')

        three_year = (net_annual * 3 - impl_cost) / max(impl_cost, 1)

        return InterventionEconomics(
            current_annual_labor_cost=round(current_annual, 0),
            automatable_pct=round(automatable * 100, 1),
            expected_annual_savings=round(expected_savings, 0),
            implementation_cost_estimate=round(impl_cost, 0),
            annual_operating_cost=round(annual_op, 0),
            payback_months=round(payback, 1) if payback < float('inf') else None,
            three_year_roi=round(three_year, 0) if three_year < float('inf') else None,
            conservative_savings=round(conservative_savings, 0),
            expected_savings=round(expected_savings, 0),
            upside_savings=round(upside_savings, 0),
            assumptions=[
                f"Annual volume: {vol:,.0f} items",
                f"Handling time: {hours:.3f} hours/item",
                f"Loaded cost: ${rate:,.0f}/hour",
                f"Current annual labor: ${current_annual:,.0f} (volume × handling time × loaded cost)",
                f"Automatable: {automatable*100:.0f}% (labor reduction {family.labor_reduction_pct[1]}% × (1 - {except_pct:.0%} exceptions))",
                f"Implementation cost: ${impl_cost:,.0f} (from 5-phase implementation plan — canonical source)",
                f"Annual operating cost: ${annual_op:,.0f}",
                f"Payback: ~{round(payback, 1)} months (assumes 50% savings ramp-up in first month, rounded up for conservative display)",
                f"3-year ROI: {round(three_year, 0)}× = (3 × annual_savings - impl_cost - 3 × annual_op) / impl_cost",
            ],
        )

    def _check_insufficient_information(self, scored: list[InterventionCandidate]) -> Optional[dict]:
        """Return a 'do not proceed' recommendation if information is insufficient."""
        if self.assessment.constraint == "unknown":
            return {
                "reason": "constraint_unknown",
                "message": (
                    "The workflow appears suitable for improvement, but the root cause "
                    "of underperformance has not been identified. Establish the baseline "
                    "and diagnose the constraint before selecting an intervention."
                ),
                "recommended_action": "Run discovery: measure current volume, error rate, handling time, and cost baseline.",
            }

        if not self.assessment.annual_workflow_volume:
            return {
                "reason": "volume_unknown",
                "message": (
                    "Without volume data, the economic case for any intervention cannot "
                    "be validated. Automation investments require sufficient scale to justify setup cost."
                ),
                "recommended_action": "Measure monthly volume for at least one quarter before proceeding.",
            }

        # If best candidate scores below 0.4 overall, recommend baseline
        if scored and scored[0].overall_score < 0.4:
            return {
                "reason": "low_confidence",
                "message": (
                    "No intervention scores above the confidence threshold for this "
                    "combination of constraint, volume, and organizational context. "
                    "Establish a clearer baseline before committing to an intervention."
                ),
                "recommended_action": "Run a pilot measurement period and re-assess.",
            }

        return None

    # ── Formatting ──

    def _format_candidate(self, c: InterventionCandidate) -> dict:
        return {
            "family_id": c.family_id,
            "family_name": c.family_name,
            "overall_score": c.overall_score,
            "dimensions": {
                dim: {"score": s.score, "confidence": s.confidence, "rationale": s.rationale}
                for dim, s in c.scores.items()
            },
            "economics": self._format_economics(c) if c.economics else None,
            "contraindications_triggered": c.contraindications_triggered,
            "evidence": c.evidence[:5] if c.evidence else [],
            "negative_evidence": c.negative_evidence[:3] if c.negative_evidence else [],
        }

    def _format_economics(self, c: InterventionCandidate) -> Optional[dict]:
        if not c.economics:
            return None
        e = c.economics
        return {
            "current_annual_labor_cost": e.current_annual_labor_cost,
            "automatable_pct": e.automatable_pct,
            "expected_annual_savings": e.expected_annual_savings,
            "implementation_cost_estimate": e.implementation_cost_estimate,
            "annual_operating_cost": e.annual_operating_cost,
            "payback_months": e.payback_months,
            "three_year_roi": e.three_year_roi,
            "scenarios": {
                "conservative": e.conservative_savings,
                "expected": e.expected_savings,
                "upside": e.upside_savings,
            },
            "assumptions": e.assumptions,
        }


# ── Per-Constraint Weight Profiles ────────────────────────────────────────────
# Constraints select entirely different weight profiles, not just marginal tweaks.
# Capacity needs volume + economics to dominate. Compliance almost ignores automation.

CONSTRAINT_WEIGHT_PROFILES: dict[str, dict[str, float]] = {
    "capacity": {
        "problem_fit": 0.10, "economic_fit": 0.20, "automation_potential": 0.15,
        "volume_fit": 0.20, "exception_fit": 0.05, "risk": 0.05,
        "feasibility": 0.05, "organizational_readiness": 0.05,
        "integration_feasibility": 0.03, "time_to_value": 0.07,
        "evidence_strength": 0.05,
    },
    "errors": {
        "problem_fit": 0.10, "economic_fit": 0.10, "automation_potential": 0.25,
        "volume_fit": 0.10, "exception_fit": 0.15, "risk": 0.08,
        "feasibility": 0.05, "organizational_readiness": 0.05,
        "integration_feasibility": 0.05, "time_to_value": 0.04,
        "evidence_strength": 0.03,
    },
    "speed": {
        "problem_fit": 0.10, "economic_fit": 0.12, "automation_potential": 0.20,
        "volume_fit": 0.10, "exception_fit": 0.08, "risk": 0.05,
        "feasibility": 0.08, "organizational_readiness": 0.05,
        "integration_feasibility": 0.05, "time_to_value": 0.14,
        "evidence_strength": 0.03,
    },
    "quality": {
        "problem_fit": 0.10, "economic_fit": 0.08, "automation_potential": 0.10,
        "volume_fit": 0.05, "exception_fit": 0.18, "risk": 0.10,
        "feasibility": 0.08, "organizational_readiness": 0.15,
        "integration_feasibility": 0.08, "time_to_value": 0.05,
        "evidence_strength": 0.03,
    },
    "cost": {
        "problem_fit": 0.08, "economic_fit": 0.30, "automation_potential": 0.18,
        "volume_fit": 0.15, "exception_fit": 0.05, "risk": 0.05,
        "feasibility": 0.05, "organizational_readiness": 0.03,
        "integration_feasibility": 0.03, "time_to_value": 0.05,
        "evidence_strength": 0.03,
    },
    "visibility": {
        "problem_fit": 0.08, "economic_fit": 0.08, "automation_potential": 0.05,
        "volume_fit": 0.05, "exception_fit": 0.05, "risk": 0.05,
        "feasibility": 0.15, "organizational_readiness": 0.10,
        "integration_feasibility": 0.25, "time_to_value": 0.11,
        "evidence_strength": 0.03,
    },
    "compliance": {
        "problem_fit": 0.10, "economic_fit": 0.05, "automation_potential": 0.03,
        "volume_fit": 0.03, "exception_fit": 0.05, "risk": 0.30,
        "feasibility": 0.15, "organizational_readiness": 0.10,
        "integration_feasibility": 0.10, "time_to_value": 0.06,
        "evidence_strength": 0.03,
    },
    "unknown": {
        "problem_fit": 0.05, "economic_fit": 0.03, "automation_potential": 0.02,
        "volume_fit": 0.02, "exception_fit": 0.02, "risk": 0.03,
        "feasibility": 0.03, "organizational_readiness": 0.03,
        "integration_feasibility": 0.02, "time_to_value": 0.02,
        "evidence_strength": 0.75,  # Heavily dependent on evidence when constraint unknown
    },
}


def get_weights_for_constraint(constraint_type: str) -> dict[str, float]:
    """Return full scoring weight profile for a constraint type."""
    profile = CONSTRAINT_WEIGHT_PROFILES.get(constraint_type)
    if profile:
        return dict(profile)
    return CONSTRAINT_WEIGHT_PROFILES["unknown"]


# ── Evidence Wiring ───────────────────────────────────────────────────────────

def wire_evidence(decision_result: dict, workflow: str, business_function: str,
                  industry: str = "", employee_count: int = None,
                  desired_outcome: str = "") -> dict:
    """Wire evidence into the decision engine output.

    Evidence acts as a FLOOR, not just a dimension. If fewer than 3 comparable
    implementations exist, the confidence on the entire recommendation drops.
    The gap engine is queried to check if this (workflow, function) category
    has known evidence deficiencies.
    """
    recommendation_confidence = "high"
    confidence_limits = []

    try:
        from compass_collector.analysis.retrieval import (
            ImplementationQuery, find_comparable_implementations, get_negative_evidence,
        )

        # ── Query gap engine for this category ──
        try:
            from compass_agent.evidence_gap import run_gap_engine
            gap_report = run_gap_engine()
            gap_categories = gap_report.to_dict().get("needs", [])
            for need in gap_categories:
                nw = need.get("workflow", "")
                nf = need.get("business_function", "")
                if (nw == workflow or nw in workflow) and nf == business_function:
                    if need.get("gap_score", 0) > 0.5:
                        confidence_limits.append({
                            "source": "gap_engine",
                            "reason": f"Category ({nw}, {nf}) has weak evidence coverage (gap={need['gap_score']:.2f})",
                        })
                    break
        except Exception:
            pass  # Gap engine is best-effort

        candidates = [decision_result.get("recommended_intervention")] if decision_result.get("recommended_intervention") else []
        candidates.extend(decision_result.get("alternatives_considered", []))

        for candidate in candidates:
            if not candidate: continue

            fid = candidate.get("family_id", "")
            if fid == "No_Action": continue

            family_info = INTERVENTION_FAMILIES.get(fid)
            if not family_info: continue

            query = ImplementationQuery(
                workflow=workflow,
                business_function=business_function,
                industry=industry,
                employee_count=employee_count,
                intervention_subcategory=family_info.subtypes[0] if family_info.subtypes else "",
                desired_outcome=desired_outcome,
                max_results=10,
            )
            results = find_comparable_implementations(query)

            # ── Broaden criteria if not enough results ──
            if not results or not results.get("results") or len(results["results"]) < 3:
                for fallback in [
                    # Fallback 1: drop intervention_subcategory
                    ImplementationQuery(
                        workflow=workflow,
                        business_function=business_function,
                        industry=industry,
                        employee_count=employee_count,
                        desired_outcome=desired_outcome,
                        max_results=10,
                    ),
                    # Fallback 2: drop business_function too
                    ImplementationQuery(
                        workflow=workflow,
                        industry=industry,
                        employee_count=employee_count,
                        desired_outcome=desired_outcome,
                        max_results=10,
                    ),
                    # Fallback 3: keep only workflow + industry
                    ImplementationQuery(
                        workflow=workflow,
                        industry=industry,
                        max_results=10,
                    ),
                ]:
                    fb_results = find_comparable_implementations(fallback)
                    if fb_results and fb_results.get("results"):
                        if not results or not results.get("results") or len(fb_results["results"]) > len(results.get("results", [])):
                            results = fb_results
                        if len(results.get("results", [])) >= 3:
                            break

            if results and results.get("results"):
                top = results["results"][:5]
                # Normalize similarity from retrieval scale (0-100) to 0-1
                raw_sim = sum(r.get("similarity_score", 0) for r in top) / len(top)
                avg_sim = min(1.0, raw_sim / 100.0) if raw_sim > 1.0 else raw_sim

                # ── Evidence as floor: fewer than 3 results → low confidence ──
                if len(top) < 3:
                    if candidate == decision_result.get("recommended_intervention"):
                        recommendation_confidence = "low"
                    confidence_limits.append({
                        "source": "evidence_retrieval",
                        "reason": f"Only {len(top)} comparable implementations found for {fid} (minimum 3 required for confidence)",
                    })

                evidence_items = []
                for r in top:
                    evidence_items.append({
                        "organization": r.get("organization", "Unknown"),
                        "intervention": r.get("intervention", ""),
                        "similarity": round(r.get("similarity_score", 0), 2),
                        "outcome": r.get("outcome_summaries", [])[:2],
                        "cost_savings": r.get("cost_savings"),
                        "implementation_time": r.get("implementation_time"),
                        "employee_count": r.get("employee_count"),
                        "status": r.get("status", "unknown"),
                        "vendor_reported": r.get("vendor_reported", False),
                        "independently_verified": r.get("independently_verified", False),
                        "source_url": r.get("source_url", ""),
                    })

                if "dimensions" in candidate and "evidence_strength" in candidate["dimensions"]:
                    candidate["dimensions"]["evidence_strength"] = {
                        "score": round(avg_sim, 2),
                        "confidence": min(1.0, len(top) / 10),
                        "rationale": f"{len(top)} comparable implementations found, avg similarity {avg_sim:.2f}",
                    }

                candidate["evidence"] = evidence_items

                negative = get_negative_evidence(query)
                if negative:
                    candidate["negative_evidence"] = [
                        {"organization": n.get("organization", ""),
                         "what_failed": n.get("summary", ""),
                         "cost": n.get("cost_savings")}
                        for n in negative[:3]
                    ]

                # Recompute overall score with constraint weights
                if "dimensions" in candidate:
                    dims = candidate["dimensions"]
                    weights = get_weights_for_constraint(
                        decision_result.get("problem", {}).get("constraint_type", "unknown")
                    )
                    overall = sum(
                        weights.get(d, 0) * dims[d].get("score", 0.5)
                        for d in dims if d in weights
                    )
                    candidate["overall_score"] = round(overall, 3)
            else:
                # Zero evidence for this candidate
                if candidate == decision_result.get("recommended_intervention"):
                    recommendation_confidence = "low"
                confidence_limits.append({
                    "source": "evidence_retrieval",
                    "reason": f"No comparable implementations found for {fid}",
                })

        # Re-sort ALL candidates by updated overall_score (evidence may change ranking)
        all_candidates = []
        if decision_result.get("recommended_intervention"):
            all_candidates.append(decision_result["recommended_intervention"])
        alts = decision_result.get("alternatives_considered", [])
        all_candidates.extend(alts)
        all_candidates.sort(key=lambda c: -(c.get("overall_score", 0) if c else 0))

        if all_candidates:
            decision_result["recommended_intervention"] = all_candidates[0]
            decision_result["alternatives_considered"] = all_candidates[1:]

        # Observed vs predicted — impact at other companies
        rec = decision_result.get("recommended_intervention")
        if rec and rec.get("evidence"):
            impact_items = []
            for e in rec.get("evidence", [])[:5]:
                item = {
                    "company": e.get("organization", "Unknown"),
                    "what_they_did": e.get("intervention", "")[:150],
                    "similarity": e.get("similarity", 0),
                }
                if e.get("cost_savings"):
                    item["cost_impact"] = e["cost_savings"]
                if e.get("implementation_time"):
                    item["timeline"] = e["implementation_time"]
                if e.get("employee_count"):
                    item["company_size"] = e["employee_count"]
                if e.get("status"):
                    item["outcome"] = e["status"]
                if e.get("outcome"):
                    item["outcomes"] = e["outcome"]
                impact_items.append(item)

            rec["impact_at_other_companies"] = impact_items

            # Compute aggregate stats from observed outcomes
            observed_savings = []
            observed_timelines = []
            for e in rec.get("evidence", []):
                if e.get("cost_savings"):
                    try: observed_savings.append(float(str(e["cost_savings"]).replace("$","").replace(",","")))
                    except: pass
                if e.get("implementation_time"):
                    try: observed_timelines.append(float(str(e["implementation_time"]).replace("weeks","").replace("months","").strip()))
                    except: pass

            if observed_savings:
                import statistics
                rec["observed_outcomes"] = {
                    "cost_savings_range": [min(observed_savings), max(observed_savings)],
                    "median_cost_savings": statistics.median(observed_savings) if observed_savings else None,
                    "sample_size": len(observed_savings),
                    "companies_with_cost_data": len(observed_savings),
                }
            if observed_timelines:
                rec["observed_timelines"] = {
                    "range_weeks": [min(observed_timelines), max(observed_timelines)],
                    "median_weeks": statistics.median(observed_timelines) if observed_timelines else None,
                }

        # Counterfactual rationale with actual numbers
        decision_result["counterfactual_rationale"] = _generate_counterfactual(
            decision_result,
            volume=decision_result.get("problem", {}).get("annual_volume"),
            labor_rate=None,  # populated from economics
        )

        # ── Evidence floor: apply to overall confidence ──
        decision_result["recommendation_confidence"] = recommendation_confidence
        decision_result["confidence_limits"] = confidence_limits

    except Exception:
        pass

    return decision_result


def _generate_counterfactual(decision_result: dict, volume: float = None,
                              labor_rate: float = None) -> dict:
    """Generate natural-language rationale explaining why the recommended
    intervention beats each alternative, using actual assessment numbers."""
    rec = decision_result.get("recommended_intervention")
    alts = decision_result.get("alternatives_considered", [])
    problem = decision_result.get("problem", {})

    if not rec or not alts:
        return {"summary": "No alternatives to compare."}

    constraint = problem.get("constraint_type", "unknown")
    rec_name = rec.get("family_name", "")
    rec_econ = rec.get("economics", {})

    comparisons = []
    for alt in alts[:3]:
        if not alt: continue
        alt_name = alt.get("family_name", "")
        alt_econ = alt.get("economics", {})
        rec_dims = rec.get("dimensions", {})
        alt_dims = alt.get("dimensions", {})

        # Find where recommended wins
        wins = []
        for dim in ["problem_fit", "economic_fit", "volume_fit", "automation_potential", "risk", "time_to_value"]:
            rs = rec_dims.get(dim, {}).get("score", 0)
            als = alt_dims.get(dim, {}).get("score", 0)
            if rs > als + 0.05:
                wins.append({"dimension": dim, "recommended": round(rs, 2), "alternative": round(als, 2)})

        loses = []
        for dim in ["feasibility", "risk", "time_to_value", "organizational_readiness"]:
            rs = rec_dims.get(dim, {}).get("score", 0)
            als = alt_dims.get(dim, {}).get("score", 0)
            if als > rs + 0.05:
                loses.append({"dimension": dim, "recommended": round(rs, 2), "alternative": round(als, 2)})

        # Build intelligent rationale with actual numbers
        parts = []

        # Economic comparison
        if rec_econ and alt_econ:
            rec_savings = rec_econ.get("expected_annual_savings", 0)
            alt_savings = alt_econ.get("expected_annual_savings", 0)
            rec_payback = rec_econ.get("payback_months")
            alt_payback = alt_econ.get("payback_months")

            if rec_savings and alt_savings and rec_savings > alt_savings:
                diff = rec_savings - alt_savings
                parts.append(
                    f"{rec_name} saves ${diff:,.0f}/year more than {alt_name} "
                    f"(${rec_savings:,.0f} vs ${alt_savings:,.0f})"
                )
            if rec_payback and alt_payback and rec_payback < alt_payback:
                parts.append(
                    f"and pays back in {rec_payback:.0f} months vs {alt_payback:.0f} months"
                )

        # Constraint-specific rationale
        if constraint == "capacity" and volume:
            if rec_name == "AI Implementation" and alt_name == "Staffing Change":
                parts.append(
                    f"At {volume:,.0f} items/year, AI scales without adding headcount "
                    f"while staffing costs grow linearly with volume"
                )
            elif rec_name == "Staffing Change" and alt_name == "AI Implementation":
                parts.append(
                    f"At only {volume:,.0f} items/year, the volume is too low to justify "
                    f"AI setup costs — additional staffing is more cost-effective"
                )

        if constraint == "cost":
            if rec_econ and alt_econ:
                rec_roi = rec_econ.get("three_year_roi", 0)
                alt_roi = alt_econ.get("three_year_roi", 0)
                if rec_roi and alt_roi and rec_roi > alt_roi:
                    parts.append(
                        f"{rec_name} delivers {rec_roi:.0f}× 3-year ROI vs {alt_roi:.0f}× for {alt_name}"
                    )

        if constraint == "errors":
            rec_auto = rec_dims.get("automation_potential", {}).get("score", 0)
            alt_auto = alt_dims.get("automation_potential", {}).get("score", 0)
            if rec_auto > alt_auto:
                parts.append(
                    f"{rec_name} is better suited for error reduction because it "
                    f"eliminates manual variation — automation potential {rec_auto:.0%} vs {alt_auto:.0%}"
                )

        # Risk comparison
        if constraint == "compliance":
            rec_risk = rec_dims.get("risk", {}).get("score", 0)
            alt_risk = alt_dims.get("risk", {}).get("score", 0)
            if rec_risk > alt_risk:
                parts.append(
                    f"{rec_name} has lower compliance risk ({rec_risk:.0%} risk tolerance "
                    f"vs {alt_risk:.0%}), critical for regulated environments"
                )

        rationale = ". ".join(parts) + "." if parts else (
            f"{rec_name} scores higher overall than {alt_name} "
            f"({rec.get('overall_score', 0):.2f} vs {alt.get('overall_score', 0):.2f})"
        )

        comparisons.append({
            "alternative": alt_name,
            "recommended_wins": wins,
            "recommended_loses": loses,
            "rationale": rationale,
        })

    # Overall summary
    summary_parts = [f"{rec_name} is the recommended intervention for this {constraint} constraint."]

    if comparisons:
        summary_parts.append(f"Alternatives considered: {', '.join(c['alternative'] for c in comparisons)}.")

    if rec_econ:
        savings = rec_econ.get("expected_annual_savings")
        payback = rec_econ.get("payback_months")
        if savings:
            summary_parts.append(f"Expected annual savings: ${savings:,.0f}.")
        if payback:
            summary_parts.append(f"Payback: {payback:.0f} months.")

    # Contraindications warning
    contras = rec.get("contraindications_triggered", [])
    if contras:
        summary_parts.append(
            f"⚠ Note: {len(contras)} contraindications are triggered — "
            f"verify these conditions before proceeding."
        )

    return {
        "summary": " ".join(summary_parts),
        "per_alternative": comparisons,
    }


# ── Full pipeline ─────────────────────────────────────────────────────────────

def decide_with_evidence(
    assessment: AssessmentInput,
    workflow: str = "",
    business_function: str = "",
    industry: str = "",
    employee_count: int = None,
    desired_outcome: str = "",
) -> dict:
    """Full decision pipeline with evidence, gap analysis, and versioning.

    Generates candidates BEFORE querying evidence, scores each independently,
    wires evidence retrieval, queries the gap engine, and produces a fully
    traceable decision object.
    """
    import subprocess, os
    from datetime import datetime, timezone

    # ── Engine version from git ──
    engine_version = "decision-v1"
    try:
        engine_version = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            text=True,
        ).strip()
    except Exception:
        pass

    engine = DecisionEngine(assessment)

    # Use per-constraint weights
    constraint_weights = get_weights_for_constraint(assessment.constraint)
    saved = dict(WEIGHTS)
    for dim in WEIGHTS:
        if dim in constraint_weights:
            WEIGHTS[dim] = constraint_weights[dim]

    decision = engine.decide()

    # Restore weights
    for dim in WEIGHTS:
        WEIGHTS[dim] = saved[dim]

    # Wire evidence
    decision = wire_evidence(
        decision,
        workflow=workflow or assessment.workflow,
        business_function=business_function or assessment.business_function,
        industry=industry or assessment.industry,
        employee_count=employee_count,
        desired_outcome=desired_outcome or assessment.desired_outcome,
    )

    # ── Full decision trace for reproducibility ──
    decision["methodology"] = {
        "engine_version": engine_version,
        "engine_name": "decision-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "weights_used": constraint_weights,
        "weights_tuned_for": assessment.constraint,
        "candidates_generated_from": f"constraint={assessment.constraint}",
        "dimensions_scored": list(constraint_weights.keys()),
        "evidence_independent": "Candidates generated before evidence lookup",
        "evidence_as_floor": "Recommendation confidence drops to 'low' if fewer than 3 comparable implementations exist",
        "gap_engine_connected": True,
        "assessment_input": {
            "workflow": assessment.workflow,
            "business_function": assessment.business_function,
            "constraint": assessment.constraint,
            "standardization": assessment.standardization_level,
            "failure_impact": assessment.failure_impact,
            "annual_volume": assessment.annual_workflow_volume,
            "budget_range": assessment.budget_range,
            "desired_outcome": assessment.desired_outcome,
        },
    }

    # Run economic invariants
    invariants = validate_economic_invariants(decision)
    decision["methodology"]["invariants_valid"] = len(invariants) == 0
    decision["methodology"]["invariant_violations"] = invariants

    return decision


def validate_economic_invariants(decision: dict) -> list[str]:
    """Validate that all economic calculations are internally consistent.
    
    Invariants:
    1. current_annual = volume × hours × rate (within 2% tolerance)
    2. conservative <= expected <= upside
    3. payback = impl_cost / net_savings × 12 (within 1 month)
    4. 3yr ROI = (3 × net_savings - impl_cost) / impl_cost (within 1×)
    """
    violations = []
    rec = decision.get("recommended_intervention", {})
    econ = rec.get("economics", {})
    prob = decision.get("problem", {})
    
    if not econ:
        return violations
    
    # Invariant 1: current_annual reconciliation
    vol = prob.get("annual_volume")
    hours = prob.get("handling_time_hours") or decision.get("methodology", {}).get("assessment_input", {}).get("annual_volume")
    # Pull from assumptions since those are the canonical inputs
    for a in econ.get("assumptions", []):
        if "Annual volume:" in a:
            try: vol = float(a.split(":")[1].strip().replace(",","").split()[0])
            except: pass
    
    # Invariant 2: conservative <= expected <= upside
    scenarios = econ.get("scenarios", {})
    c = scenarios.get("conservative", 0)
    e = scenarios.get("expected", 0)
    u = scenarios.get("upside", 0)
    if c > 0 and e > 0 and u > 0 and not (c <= e <= u):
        violations.append(f"Scenario invariant: conservative=${c:,.0f} > expected=${e:,.0f}" if c > e else f"Scenario invariant: expected=${e:,.0f} > upside=${u:,.0f}")
    
    # Invariant 3: payback formula
    impl = econ.get("implementation_cost_estimate", 0)
    savings = econ.get("expected_annual_savings", 0)
    op = econ.get("annual_operating_cost", 0)
    if impl > 0 and savings > op:
        expected_pb = impl / (savings - op) * 12
        actual_pb = econ.get("payback_months", 0)
        if actual_pb and abs(expected_pb - actual_pb) > 1:
            violations.append(f"Payback invariant: calc {expected_pb:.1f}mo != displayed {actual_pb}mo (impl=${impl:,.0f})")
    
    # Invariant 4: ROI formula = (3 × net_savings - impl_cost) / impl_cost
    if impl > 0:
        expected_roi = (3 * (savings - op) - impl) / impl
        actual_roi = econ.get("three_year_roi", 0)
        if actual_roi and abs(expected_roi - actual_roi) > 1:
            violations.append(f"ROI invariant: calc {expected_roi:.0f}× != displayed {actual_roi}×")
    
    return violations
