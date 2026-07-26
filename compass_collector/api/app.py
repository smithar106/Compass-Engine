import logging
import sys
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
        "version": "3.0.0",
        "database": "collector_v3.db",
    }


@app.post("/api/recommendations")
def create_recommendation(req: InvestigationRequest):
    import traceback
    try:
        result = run_recommendation(req)
        return RecommendationResponse(**result.model_dump())
    except Exception as e:
        logger.error(f"Recommendation failed: {e}")
        logger.error(traceback.format_exc())
        return {"error": str(e), "type": "engine_error"}
