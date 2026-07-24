import uuid
from datetime import datetime

from compass_collector.models.source import SourceRegistry
from compass_collector.database import get_session


class SourceDiscoveryEngine:

    def register_source(self, config: dict) -> SourceRegistry:
        session = get_session()
        try:
            existing = session.query(SourceRegistry).filter_by(
                source_domain=config.get("source_domain", "")
            ).first()
            if existing:
                for k, v in config.items():
                    if hasattr(existing, k) and v is not None:
                        setattr(existing, k, v)
                session.commit()
                return existing

            src = SourceRegistry(
                id=str(uuid.uuid4()),
                source_domain=config.get("source_domain", ""),
                publisher=config.get("publisher", ""),
                source_category=config.get("source_category", ""),
                base_url=config.get("base_url", ""),
                discovery_method=config.get("discovery_method", "manual"),
                access_method=config.get("access_method", "public"),
                authentication_required=config.get("authentication_required", False),
                robots_status=config.get("robots_status", "unknown"),
                terms_status=config.get("terms_status", "unknown"),
                license_notes=config.get("license_notes", ""),
                crawl_frequency=config.get("crawl_frequency", "weekly"),
                rate_limit=config.get("rate_limit", 1.0),
                parser_type=config.get("parser_type", "html"),
                priority=config.get("priority", 5),
                reliability_tier=config.get("reliability_tier", 3),
                enabled=config.get("enabled", True)
            )
            session.add(src)
            session.commit()
            return src
        finally:
            session.close()

    def import_yaml(self, path: str) -> list[SourceRegistry]:
        import yaml
        with open(path) as f:
            sources = yaml.safe_load(f)
        results = []
        for src in sources.get("sources", []):
            results.append(self.register_source(src))
        return results

    def list_sources(self, enabled_only: bool = True) -> list[SourceRegistry]:
        session = get_session()
        try:
            q = session.query(SourceRegistry)
            if enabled_only:
                q = q.filter_by(enabled=True)
            return q.order_by(SourceRegistry.priority).all()
        finally:
            session.close()

    def get_source(self, source_id: str) -> SourceRegistry:
        session = get_session()
        try:
            return session.query(SourceRegistry).filter_by(id=source_id).first()
        finally:
            session.close()

    def disable_source(self, source_id: str):
        session = get_session()
        try:
            src = session.query(SourceRegistry).filter_by(id=source_id).first()
            if src:
                src.enabled = False
                session.commit()
        finally:
            session.close()
