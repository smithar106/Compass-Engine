from datetime import datetime
from sqlalchemy import Column, String, Text, Boolean, DateTime, Integer, JSON
from compass_collector.database import Base


class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True)
    source_registry_id = Column(String, index=True)
    url = Column(String, nullable=False)
    canonical_url = Column(String, default="")
    title = Column(String, default="")
    publisher = Column(String, default="")
    author = Column(String, default="")
    publication_date = Column(DateTime, nullable=True)
    modified_date = Column(DateTime, nullable=True)
    retrieved_at = Column(DateTime, default=datetime.utcnow)
    document_type = Column(String, default="")
    language = Column(String, default="")
    content_hash = Column(String, index=True)
    raw_html_path = Column(String, default="")
    raw_file_path = Column(String, default="")
    clean_text_path = Column(String, default="")
    cleaned_text = Column(Text, default="")
    screenshot_path = Column(String, default="")
    access_restrictions = Column(String, default="")
    license_notes = Column(Text, default="")
    crawl_status = Column(String, default="pending")
    parser_version = Column(String, default="1.0")
    doc_metadata = Column("doc_metadata", JSON, default=dict)
    version = Column(Integer, default=1)
    prev_version_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
