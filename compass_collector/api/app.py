import os
import logging
from pathlib import Path
from fastapi import FastAPI
from compass_collector.api.schemas import InvestigationRequest, RecommendationResponse
from compass_collector.api.service import run_recommendation
from compass_collector.database import get_session
from compass_collector.models.intervention import InterventionRecord
from compass_collector.config.settings import DATA_DIR, DATABASE_URL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("compass-engine")

app = FastAPI(
    title="Compass Recommendation Engine",
    version="3.0.0",
    docs_url="/docs",
)


@app.on_event("startup")
def startup_log():
    db_path = DATA_DIR / "collector_v3.db"
    logger.info("=" * 60)
    logger.info("COMPASS ENGINE STARTUP")
    logger.info(f"Database URL: {DATABASE_URL}")
    logger.info(f"Database path: {db_path}")
    logger.info(f"Database exists: {db_path.exists()}")
    if db_path.exists():
        logger.info(f"Database size: {db_path.stat().st_size / 1024 / 1024:.1f} MB")
    try:
        session = get_session()
        total = session.query(InterventionRecord).count()
        successful = session.query(InterventionRecord).filter(
            InterventionRecord.result_status == "successful"
        ).count()
        failed = session.query(InterventionRecord).filter(
            InterventionRecord.result_status.in_(["failed", "abandoned"])
        ).count()
        logger.info(f"Total records: {total}")
        logger.info(f"  Successful: {successful}")
        logger.info(f"  Failed/Abandoned: {failed}")
        session.close()
    except Exception as e:
        logger.warning(f"Could not query database: {e}")
    logger.info("=" * 60)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "compass-recommendation",
        "version": "3.0.0",
        "database": "collector_v3.db",
    }


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
