from datetime import datetime
from sqlalchemy import Column, String, Text, Boolean, DateTime, Float, Integer
from compass_collector.database import Base


class SourceRegistry(Base):
    __tablename__ = "source_registry"

    id = Column(String, primary_key=True)
    source_domain = Column(String, nullable=False, index=True)
    publisher = Column(String, default="")
    source_category = Column(String, default="")
    base_url = Column(String, default="")
    discovery_method = Column(String, default="")
    access_method = Column(String, default="")
    authentication_required = Column(Boolean, default=False)
    robots_status = Column(String, default="")
    terms_status = Column(String, default="")
    license_notes = Column(Text, default="")
    crawl_frequency = Column(String, default="")
    rate_limit = Column(Float, default=1.0)
    parser_type = Column(String, default="html")
    priority = Column(Integer, default=5)
    reliability_tier = Column(Integer, default=3)
    enabled = Column(Boolean, default=True)
    last_crawled_at = Column(DateTime, nullable=True)
    last_success_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
