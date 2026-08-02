import logging
import sys
import uuid
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from compass_collector.api.schemas import (
    InvestigationRequest,
    RecommendationResponse,
    InterventionSelectionRequest,
    InterventionSelectionResponse,
)
from compass_collector.api.service import run_recommendation
from compass_collector.api.storage import (
    load_recommendation,
    save_selection,
    load_selection,
    load_selection_by_recommendation,
    load_score_breakdown,
)
from compass_collector.api.report import generate_report_html, generate_report_pdf
from compass_collector.database import get_session, init_db
from compass_collector.models.intervention import InterventionRecord, MetricRecord, PassageRecord
from compass_collector.models.analysis_session import AnalysisSession  # noqa: F401 — registers the table
from compass_collector.models.walkthrough import (  # noqa: F401 — registers the tables
    ImplementationPlan,
    ImplementationRequest,
    SavedDecision,
)
from compass_collector.api.evidence_tier import classify_evidence_tier
from compass_collector.config.settings import DATA_DIR, DATABASE_URL
from compass_collector.implementation.router import router as implementation_router
from compass_collector.api.analyze_router import router as analyze_router
from compass_collector.api.walkthrough_router import router as walkthrough_router
from compass_collector.api.organization_router import router as organization_router
from compass_collector.api.enrichment_router import router as enrichment_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("compass-engine")

app = FastAPI(
    title="Compass Recommendation Engine",
    version="3.1.0",
    docs_url="/docs",
)

app.include_router(implementation_router)
app.include_router(analyze_router)
app.include_router(walkthrough_router)
app.include_router(organization_router)
app.include_router(enrichment_router)

_metadata_cache = None


def _compute_metadata() -> dict:
    db_path = DATA_DIR / "collector_v3.db"
    session = get_session()
    try:
        records = session.query(InterventionRecord).all()
        metrics_by_id: dict = {}
        for m in session.query(MetricRecord).all():
            metrics_by_id.setdefault(m.intervention_id, []).append(m)
        passages_by_id: dict = {}
        for p in session.query(PassageRecord).all():
            passages_by_id.setdefault(p.intervention_id, []).append(p)

        gold = silver = bronze = 0
        unique_orgs: set = set()
        industries: set = set()
        for rec in records:
            tier = classify_evidence_tier(rec, metrics_by_id.get(rec.id, []), passages_by_id.get(rec.id, []))
            if tier == "gold":
                gold += 1
            elif tier == "silver":
                silver += 1
            elif tier == "bronze":
                bronze += 1
            if rec.organization_name:
                unique_orgs.add(rec.organization_name)
            for ind in rec.organization_industry or []:
                if ind:
                    industries.add(str(ind).lower())

        # Measured outcomes = quantified metric records (percentage or absolute change).
        measured_outcomes = (
            session.query(MetricRecord)
            .filter((MetricRecord.percentage_change.isnot(None)) | (MetricRecord.absolute_change.isnot(None)))
            .count()
        )

        last_published_at = ""
        if db_path.exists():
            mtime = db_path.stat().st_mtime
            last_published_at = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()

        return {
            "dataset_version": "collector_v3",
            "published_records": len(records),
            "unique_organizations": len(unique_orgs),
            "industries": len(industries),
            "measured_outcomes": measured_outcomes,
            "decision_questions": 8,
            "gold": gold,
            "silver": silver,
            "bronze": bronze,
            "last_published_at": last_published_at,
            "engine_version": "3.1.0",
        }
    finally:
        session.close()


@app.get("/api/metadata")
def get_metadata():
    global _metadata_cache
    if _metadata_cache is None:
        _metadata_cache = _compute_metadata()
    return _metadata_cache


@app.on_event("startup")
def startup_log():
    db_path = DATA_DIR / "collector_v3.db"
    logger.info("=" * 60)
    logger.info("COMPASS ENGINE STARTUP")
    logger.info(f"Database URL: {DATABASE_URL}")
    logger.info(f"Database file: {db_path}")
    logger.info(f"Database exists: {db_path.exists()}")
    if db_path.exists():
        logger.info(f"Database size: {db_path.stat().st_size / 1024 / 1024:.1f} MB")
        logger.info(f"Database modified: {db_path.stat().st_mtime}")
    else:
        import urllib.request
        urls = [
            "https://media.githubusercontent.com/media/smithar106/Compass-Engine/main/data/collector_v3.db",
            "https://raw.githubusercontent.com/smithar106/Compass-Engine/main/data/collector_v3.db",
        ]
        downloaded = False
        for url in urls:
            try:
                logger.info(f"Attempting download from: {url}")
                urllib.request.urlretrieve(url, str(db_path))
                if db_path.exists() and db_path.stat().st_size > 0:
                    logger.info(f"Downloaded collector_v3.db ({db_path.stat().st_size / 1024 / 1024:.1f} MB)")
                    downloaded = True
                    break
            except Exception as dl_e:
                logger.warning(f"Download failed: {dl_e}")
        if not downloaded or not db_path.exists():
            logger.error("FATAL: Could not download collector_v3.db. Engine cannot start without a database.")
            sys.exit(1)

    session = None
    try:
        init_db()
        session = get_session()
        total = session.query(InterventionRecord).count()
        if total == 0:
            logger.error("FATAL: Database is empty. Engine cannot start without records.")
            sys.exit(1)

        tier1 = session.query(InterventionRecord).filter(
            InterventionRecord.result_status.in_(["successful", "partial"])
        ).count()
        tier2 = session.query(InterventionRecord).filter(
            InterventionRecord.result_status == "unknown"
        ).count()
        tier3 = session.query(InterventionRecord).filter(
            InterventionRecord.result_status.in_(["failed", "abandoned"])
        ).count()
        source_generations = session.query(
            InterventionRecord.extraction_model
        ).distinct().all()
        logger.info(f"Total records: {total}")
        logger.info(f"  Tier 1 (successful/partial): {tier1}")
        logger.info(f"  Tier 2 (unknown): {tier2}")
        logger.info(f"  Tier 3 (failed/abandoned): {tier3}")
        logger.info(f"  Source generations: {[g[0] for g in source_generations if g[0]]}")
        logger.info(f"  Schema version: v3")
    except Exception as e:
        logger.error(f"FATAL: Could not query database: {e}")
        sys.exit(1)
    finally:
        if session:
            session.close()
    logger.info("=" * 60)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "compass-recommendation",
        "version": "3.1.0",
        "database": "collector_v3.db",
    }


@app.post("/api/recommendations", response_model=RecommendationResponse)
def create_recommendation(req: InvestigationRequest):
    return run_recommendation(req)


@app.get("/api/recommendations/{rec_id}")
def get_recommendation(rec_id: str):
    data = load_recommendation(rec_id)
    if not data:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return data


@app.get("/api/recommendations/{rec_id}/report", response_class=HTMLResponse)
def get_report_html(rec_id: str):
    data = load_recommendation(rec_id)
    if not data:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    html = generate_report_html(data)
    return html


@app.get("/api/recommendations/{rec_id}/report.pdf")
def get_report_pdf(rec_id: str):
    data = load_recommendation(rec_id)
    if not data:
        raise HTTPException(status_code=404, detail="Recommendation not found")

    pdf_bytes = generate_report_pdf(data)
    if pdf_bytes is None:
        html = generate_report_html(data)
        return HTMLResponse(content=html)

    today = datetime.utcnow().strftime("%Y-%m-%d")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="compass-recommendation-{today}.pdf"',
        },
    )


@app.post("/api/recommendations/{rec_id}/select")
def select_intervention(rec_id: str, req: InterventionSelectionRequest):
    data = load_recommendation(rec_id)
    if not data:
        raise HTTPException(status_code=404, detail="Recommendation not found")

    existing = load_selection_by_recommendation(rec_id)
    if existing:
        raise HTTPException(status_code=409, detail="Intervention already selected for this recommendation")

    scored = data.get("scored_interventions", [])
    selected = next((s for s in scored if s.get("intervention_id") == req.selected_intervention_id), None)
    if not selected:
        raise HTTPException(status_code=400, detail="Selected intervention not found in recommendation results")

    response = InterventionSelectionResponse(
        selection_id=str(uuid.uuid4()),
        recommendation_id=rec_id,
        selected_intervention_id=req.selected_intervention_id,
        selected_intervention_name=selected.get("intervention_name", ""),
        recommendation_version=data.get("_schema_version", ""),
        scoring_config_version=data.get("scoring_config_version", ""),
        scoring_weights=data.get("scoring_weights_used", {}),
        user_inputs_snapshot=data.get("assessment_summary", {}),
        score_breakdown_snapshot=selected.get("score_breakdown", {}),
        evidence_ids_used=[c.get("organization_name", "") for c in selected.get("comparable_implementations", [])],
        selection_timestamp=datetime.now(timezone.utc).isoformat(),
        status="active",
    )
    save_selection(response)
    return response


@app.get("/api/recommendations/{rec_id}/selection")
def get_selection(rec_id: str):
    sel = load_selection_by_recommendation(rec_id)
    if not sel:
        raise HTTPException(status_code=404, detail="No selection found for this recommendation")
    return sel


@app.get("/api/recommendations/{rec_id}/breakdown")
def get_score_breakdown(rec_id: str):
    stored = load_score_breakdown(rec_id)
    if stored:
        return stored
    data = load_recommendation(rec_id)
    if not data:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    scored = data.get("scored_interventions", [])
    return {
        "recommendation_id": rec_id,
        "scored_interventions": [
            {
                "intervention_id": s.get("intervention_id"),
                "intervention_name": s.get("intervention_name"),
                "match_score": s.get("match_score"),
                "score_breakdown": s.get("score_breakdown"),
            }
            for s in scored
        ],
    }


@app.get("/api/recommendations/{rec_id}/comparisons")
def get_comparisons(rec_id: str):
    data = load_recommendation(rec_id)
    if not data:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    scored = data.get("scored_interventions", [])
    return {
        "recommendation_id": rec_id,
        "comparisons": [
            {
                "intervention_id": s.get("intervention_id"),
                "intervention_name": s.get("intervention_name"),
                "comparable_implementations": s.get("comparable_implementations", []),
            }
            for s in scored
        ],
    }


@app.post("/api/recommendations/{rec_id}/regenerate")
def regenerate_recommendation(rec_id: str, req: InvestigationRequest):
    from compass_collector.api.service import run_recommendation
    new_response = run_recommendation(req)
    return new_response
