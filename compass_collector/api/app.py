from fastapi import FastAPI
from compass_collector.api.schemas import InvestigationRequest, RecommendationResponse
from compass_collector.api.service import run_recommendation

app = FastAPI(
    title="Compass Recommendation Engine",
    version="2.0.0",
    docs_url="/docs",
)


@app.get("/health")
def health():
    return {"status": "ok", "service": "compass-recommendation", "version": "2.0.0"}


@app.post("/api/recommendations", response_model=RecommendationResponse)
def create_recommendation(req: InvestigationRequest):
    return run_recommendation(req)


@app.post("/api/recommendations/demo", response_model=RecommendationResponse)
def demo_recommendation(scenario_name: str = ""):
    scenarios = {
        "cloud_cost": InvestigationRequest(
            workflow="cloud_infrastructure_management",
            business_function="operations",
            industry="technology",
            company_size="500",
            desired_outcome="cost",
        ),
        "support_automation": InvestigationRequest(
            workflow="ticketing",
            business_function="customer_support",
            industry="saas",
            company_size="200",
            desired_outcome="response_time",
        ),
        "invoice_processing": InvestigationRequest(
            workflow="invoice_processing",
            business_function="finance",
            industry="financial_services",
            company_size="1000",
            desired_outcome="cost",
        ),
        "lead_qualification": InvestigationRequest(
            workflow="lead_qualification",
            business_function="sales",
            industry="technology",
            company_size="300",
            desired_outcome="conversion_rate",
        ),
        "hr_onboarding": InvestigationRequest(
            workflow="onboarding",
            business_function="human_resources",
            industry="healthcare",
            company_size="2000",
            desired_outcome="time",
        ),
    }
    req = scenarios.get(scenario_name, scenarios["lead_qualification"])
    return run_recommendation(req)
