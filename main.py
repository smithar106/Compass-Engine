#!/usr/bin/env python3
"""
Compass Collector — Intervention Evidence Collection System

Usage:
    main.py init                 Initialize database
    main.py sources import <yaml>
    main.py sources list         List registered sources
    main.py discover [--problem <text>]
    main.py crawl [--source <id>] [--limit <n>]
    main.py parse                Extract text from crawled documents
    main.py extract              Detect interventions and extract metrics
    main.py validate             Show quality flags
    main.py deduplicate          Find duplicate documents
    main.py export [--format jsonl|csv]
    main.py status               Show system status
    main.py retry                Reset failed crawls to pending
    main.py reset                Delete database
    main.py demo                 Run full demo with sample data
    main.py pipeline             Run full pipeline (crawl → parse → extract → dedup → export)
"""

import sys
from compass_collector.cli.main import *
from compass_collector.database import init_db


def get_opencli_sources() -> list[dict]:
    """Sources focused on real organizational implementations with measured outcomes.
    Mission: Collect evidence of operational interventions and measured business outcomes.
    Reject: Academic papers, algorithm proposals, general news without implementation evidence."""

    sources = []

    # ── CASE STUDY SEARCHES (highest yield) ──
    case_study_queries = [
        # General case study searches
        "case study implementation results ROI",
        "digital transformation before after results",
        "migration saved costs case study",
        "workflow automation reduced time",
        "process redesign improved efficiency",
        "cloud migration cost savings enterprise",
        "software implementation outcomes",
        "operational transformation measured results",
        "automation deployment metrics results",
        "RPA implementation before after",
        "AI deployed enterprise results metrics",
        "digital operations improvement case study",
        "supply chain optimization savings",
        "customer service automation results",
        "predictive maintenance savings case study",
        "legacy system migration outcomes",
        "lean implementation manufacturing results",
    ]
    for q in case_study_queries:
        # Try multiple sources for each query
        for source_name in ["hn", "reddit", "devto"]:
            command_map = {
                "hn": f'hackernews search "{q}" --limit 20',
                "reddit": f'reddit search "{q}" --limit 20',
                "devto": f'devto search "{q}" --limit 20',
            }
            key = q[:15].replace(" ", "_")
            sources.append({
                "source": f"{source_name}-cs-{key}",
                "command": command_map[source_name],
                "limit": 20, "intervention_type": "case_study", "problem": "implementation"
            })

    # ── VENDOR CASE STUDIES (tier 1 gold when outcomes are real) ──
    vendor_cs_queries = [
        "AWS customer story migration savings",
        "Microsoft customer success digital transformation",
        "Salesforce implementation results",
        "ServiceNow automation outcomes",
        "UiPath RPA results case study",
        "IBM client success measured outcomes",
        "SAP implementation ROI case study",
        "Oracle cloud migration savings",
        "Workday HR transformation results",
        "Snowflake data migration case study",
        "Datadog monitoring implementation results",
        "Cloudflare migration performance improvement",
        "Stripe payment optimization revenue",
        "Twilio customer engagement results",
        "HubSpot implementation ROI case study",
        "Zendesk customer service improvement",
    ]
    for q in vendor_cs_queries:
        key = q[:20].replace(" ", "_")
        sources.append({
            "source": f"vendor-{key}",
            "command": f'google-scholar search "{q}" --limit 10',
            "limit": 10, "intervention_type": "vendor_case_study", "problem": "implementation"
        })

    # ── CONSULTING / INDUSTRY RESEARCH (tier 2 silver) ──
    consulting_queries = [
        "McKinsey digital transformation results",
        "BCG AI implementation enterprise",
        "Deloitte automation adoption survey",
        "Accenture case study implementation",
        "Gartner RPA adoption failure rate",
        "Forrester digital operations study",
        "Bain transformation results enterprise",
        "McKinsey operational improvement study",
    ]
    for q in consulting_queries:
        key = q[:20].replace(" ", "_")
        sources.append({
            "source": f"consulting-{key}",
            "command": f'google-scholar search "{q}" --limit 10',
            "limit": 10, "intervention_type": "industry_research", "problem": "research"
        })

    # ── HackerNews - business/operations focused ──
    for section in ["top", "show"]:
        sources.append({
            "source": f"hackernews-{section}",
            "command": f"hackernews {section} --limit 30",
            "limit": 30, "intervention_type": "general", "problem": "technology"
        })

    hn_business_queries = [
        "case study", "implementation", "migration", "automation",
        "cloud costs", "reduced", "saved", "ROI",
        "devops deployment", "digital transformation",
        "infrastructure migration", "cost optimization",
        "incident response", "monitoring", "scaling",
    ]
    for q in hn_business_queries:
        sources.append({
            "source": f"hn-{q[:15].replace(' ', '_')}",
            "command": f'hackernews search "{q}" --limit 25',
            "limit": 25, "intervention_type": "business", "problem": "implementation"
        })

    # ── Reddit - operations/business subreddits ──
    reddit_business_subs = [
        "devops", "ExperiencedDevs", "sysadmin", "ITManagers",
        "aws", "kubernetes", "docker", "SiteReliabilityEngineering",
        "programming", "product_design", "userexperience",
        "startups", "entrepreneur", "SaaS", "consulting",
        "business", "operations", "supplychain", "logistics",
        "manufacturing", "healthcare", "fintech",
        "dataengineering", "analytics", "datavisualization",
        "sales", "marketing", "digital_marketing",
    ]
    for sub in reddit_business_subs:
        sources.append({
            "source": f"reddit-r/{sub}",
            "command": f"reddit subreddit {sub} --limit 25",
            "limit": 25, "intervention_type": sub, "problem": "operations"
        })

    reddit_impl_queries = [
        "implemented OR migrated OR deployed OR automated",
        "saved OR reduced OR improved OR increased",
        "migration OR cloud OR on-prem",
        "workflow OR process OR automation",
        "monitoring OR observability OR incident",
        "cost optimization OR savings OR efficiency",
        "database migration OR schema change OR refactor",
        "CI/CD OR deployment OR pipeline",
    ]
    for q in reddit_impl_queries:
        sources.append({
            "source": f"reddit-impl-{q[:15].replace(' ', '_')}",
            "command": f'reddit search "{q}" --limit 20',
            "limit": 20, "intervention_type": "implementation", "problem": "operations"
        })

    # ── Dev.to - implementation-focused tags ──
    devto_impl_tags = [
        "devops", "cloud", "aws", "azure", "gcp", "kubernetes",
        "docker", "terraform", "cicd", "monitoring", "observability",
        "database", "migration", "backend", "architecture",
        "security", "performance", "automation", "productivity",
        "startup", "saas", "api", "testing", "deployment",
    ]
    for tag in devto_impl_tags:
        sources.append({
            "source": f"devto-{tag}",
            "command": f"devto tag {tag} --limit 20",
            "limit": 20, "intervention_type": tag, "problem": "implementation"
        })

    # ── ArXiv - VERY restricted: only operations research / economics ──
    # Academic papers are tier 3 (bronze) - supporting evidence only
    for category in ["econ.EM", "q-fin.RM", "cs.CY", "cs.HC", "stat.AP"]:
        sources.append({
            "source": f"arxiv-{category}",
            "command": f"arxiv recent {category} --limit 10",
            "limit": 10, "intervention_type": "academic", "problem": "research"
        })

    return sources


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1]

    if cmd == "init":
        cmd_init()
    elif cmd == "sources" and len(sys.argv) >= 3:
        if sys.argv[2] == "import":
            cmd_sources_import(sys.argv[3])
        elif sys.argv[2] == "list":
            cmd_sources_list()
    elif cmd == "discover":
        problem = None
        if "--problem" in sys.argv:
            idx = sys.argv.index("--problem")
            problem = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None
        cmd_discover(problem)
    elif cmd == "crawl":
        source_id = None
        limit = None
        if "--source" in sys.argv:
            idx = sys.argv.index("--source")
            source_id = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None
        if "--limit" in sys.argv:
            idx = sys.argv.index("--limit")
            limit = int(sys.argv[idx + 1]) if idx + 1 < len(sys.argv) else None
        init_db()
        cmd_crawl(source_id, limit)
    elif cmd == "parse":
        init_db()
        cmd_parse()
    elif cmd == "extract":
        init_db()
        cmd_extract()
    elif cmd == "validate":
        init_db()
        cmd_validate()
    elif cmd == "deduplicate":
        init_db()
        cmd_deduplicate()
    elif cmd == "export":
        fmt = "jsonl"
        if "--format" in sys.argv:
            idx = sys.argv.index("--format")
            fmt = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "jsonl"
        init_db()
        cmd_export(fmt)
    elif cmd == "status":
        init_db()
        cmd_status()
    elif cmd == "retry":
        init_db()
        cmd_retry()
    elif cmd == "reset":
        cmd_reset()
    elif cmd == "pipeline":
        init_db()
        cmd_crawl()
        cmd_parse()
        cmd_extract()
        cmd_deduplicate()
        cmd_export("jsonl")
    elif cmd == "scale":
        target = 2000
        if "--target" in sys.argv:
            idx = sys.argv.index("--target")
            target = int(sys.argv[idx + 1])
        max_queries = 200
        if "--queries" in sys.argv:
            idx = sys.argv.index("--queries")
            max_queries = int(sys.argv[idx + 1])
        from compass_collector.scraper.scale_pipeline import ScaleCollectionPipeline
        ScaleCollectionPipeline().run(target_records=target, max_queries=max_queries)
    elif cmd == "opencli":
        target = 5000
        fetch = True
        if "--no-fetch" in sys.argv:
            fetch = False
        from compass_collector.scraper.opencli_bridge import OpenCLIBridge
        bridge = OpenCLIBridge()
        sources = get_opencli_sources()
        print(f"=== OPENCLI Collection ===")
        print(f"Target: {target} records")
        print(f"Sources: {len(sources)} commands\n")
        for s in sources:
            print(f"  [{s['source']:25s}] {s['command']}")
        print(f"\nCollecting...")
        items = bridge.collect_all(sources, fetch_texts=fetch)
        print(f"\nCollected {len(items)} items. Processing into DB...")
        bridge.process_into_collector(items, target)
        print(f"\nExporting...")
        bridge.export()
        print(f"Done! Stats: {bridge.stats}")
    elif cmd == "validate":
        init_db()
        from compass_collector.scraper.completeness_validator import CompletenessValidator
        print(CompletenessValidator().report())
    elif cmd == "demo":
        run_demo()
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)


def run_demo():
    from compass_collector.pipeline.orchestrator import PipelineOrchestrator
    from compass_collector.config.settings import DATA_DIR, BASE_DIR
    from compass_collector.database import get_session
    from compass_collector.models.source import SourceRegistry

    init_db()
    pipe = PipelineOrchestrator()

    # Register sample sources
    sample_sources = [
        {"source_domain": "example.edu", "publisher": "Stanford University",
         "source_category": "academic", "base_url": "https://example.edu/ai-case-study",
         "discovery_method": "manual", "access_method": "public", "priority": 1, "reliability_tier": 1},
        {"source_domain": "consulting-co.com", "publisher": "McKinsey & Company",
         "source_category": "consulting", "base_url": "https://consulting-co.com/report",
         "discovery_method": "manual", "access_method": "public", "priority": 3, "reliability_tier": 2},
        {"source_domain": "vendor-platform.io", "publisher": "TechVendor Inc.",
         "source_category": "vendor", "base_url": "https://vendor-platform.io/case-studies",
         "discovery_method": "manual", "access_method": "public", "priority": 5, "reliability_tier": 4},
    ]
    for src in sample_sources:
        pipe.discovery.register_source(src)
    print(f"Registered {len(sample_sources)} sample sources.")

    # Create sample documents with intervention evidence directly
    from compass_collector.models.document import Document
    from compass_collector.engine.crawl import CrawlEngine
    import uuid
    import hashlib
    from datetime import datetime

    session = get_session()
    try:
        samples = [
            {
                "source": "example.edu",
                "title": "AI-Assisted Customer Support Reduces Resolution Time by 40%",
                "text": "Stanford University conducted a 6-month study of AI-assisted customer support across 12 enterprise organizations. The intervention used a generative AI chatbot with human-in-the-loop review for complex cases. Results: average resolution time decreased from 24 hours to 14.4 hours (40% improvement). Customer satisfaction scores improved from 72 to 88. The pilot involved 120 support agents across 3 departments. Implementation cost was $450,000. The project was completed on time and under budget. The vendor reported these results through their annual impact report. No control group was used.",
                "families": ["generative_ai", "human_in_the_loop_ai", "ai_assisted_work"]
            },
            {
                "source": "consulting-co.com",
                "title": "Process Redesign in Manufacturing: Failed RPA Implementation",
                "text": "McKinsey report on a failed RPA implementation at a mid-sized manufacturing company. The organization attempted to automate their invoice processing workflow using robotic process automation. The project was abandoned after 8 months at a cost of $1.2M. Root causes included lack of executive sponsorship, inadequate change management, and poor documentation quality. The existing process was not standardized before automation. No measurable improvement was observed in processing time or error rates. The company reverted to manual processing.",
                "families": ["robotic_process_automation", "failed"],
                "status": "failed"
            },
            {
                "source": "vendor-platform.io",
                "title": "Cloud Migration Delivers 30% Cost Savings for Enterprise",
                "text": "TechVendor case study: Enterprise healthcare provider migrated legacy on-premise CRM to cloud-based solution. The migration took 14 weeks and cost $2.3M. Results: 30% reduction in total cost of ownership, 45% improvement in system uptime (from 96% to 99.4%), and 22% increase in user adoption. The project involved reallocating 8 IT staff to new roles. The vendor claims a payback period of 18 months. Independent audit confirmed infrastructure savings but noted user adoption was measured via system login data only.",
                "families": ["new_software_implementation", "existing_software_optimization"],
                "status": "successful"
            },
            {
                "source": "example.edu",
                "title": "Staffing Increase Improves Call Center Metrics, But ROI Questionable",
                "text": "Academic study of a staffing increase intervention at a regional bank's call center. Headcount was increased by 35% (from 80 to 108 agents). Results: Average speed to answer improved from 8 minutes to 2.5 minutes. Call abandonment rate dropped from 18% to 6%. Customer satisfaction increased from 74 to 81. However, cost per call increased by 22% due to additional headcount expense. The study concluded that while service levels improved, the return on investment was negative when accounting for full loaded costs. The bank did not implement this as a permanent change.",
                "families": ["staffing_increases"],
                "status": "neutral"
            },
            {
                "source": "consulting-co.com",
                "title": "Predictive AI for Supply Chain: Mixed Results Across 40 Companies",
                "text": "BCG analysis of predictive AI adoption across 40 manufacturing companies. 12 companies achieved significant inventory reduction (averaging 23%). 18 companies saw moderate improvement (5-10%). 10 companies reported no measurable improvement or abandoned the project. Key success factors: data quality, dedicated implementation team, and executive sponsorship. Key failure conditions: poor data infrastructure and inadequate training. Average implementation cost was $2.8M with average payback of 14 months for successful cases. Vendor-reported results were 2.5x higher than independent assessments.",
                "families": ["predictive_ai", "hybrid_combination"],
                "status": "partial"
            }
        ]

        base_ts = datetime(2025, 6, 1)

        for i, s in enumerate(samples):
            ts = base_ts.replace(day=base_ts.day + i)
            content_bytes = s["text"].encode()
            content_hash = hashlib.sha256(content_bytes).hexdigest()

            raw_dir = DATA_DIR / "raw" / "clean"
            raw_dir.mkdir(parents=True, exist_ok=True)
            text_path = raw_dir / f"{content_hash[:16]}.txt"
            text_path.write_text(s["text"])

            src = session.query(SourceRegistry).filter_by(
                source_domain=s["source"]
            ).first()

            doc = Document(
                id=str(uuid.uuid4()),
                source_registry_id=src.id if src else "",
                url=f"https://{s['source']}/study/{i}",
                title=s["title"],
                content_hash=content_hash,
                clean_text_path=str(text_path),
                document_type="html",
                crawl_status="success",
                retrieved_at=ts
            )
            session.add(doc)

        session.commit()
    finally:
        session.close()

    print("Created 5 sample documents with intervention evidence.")

    # Run extraction
    count = pipe.process_pending()
    print(f"Extracted interventions from {count} documents.")

    # Run deduplication
    result = pipe.deduplicate()
    print(f"Deduplication: {result['exact']} exact, {result['near']} near, {result['same_study']} same study")

    # Export
    pipe.export(["jsonl"])
    pipe.export(["csv"])

    # Status
    cmd_status()

    print("\n=== Demo Complete ===")
    exports = DATA_DIR / "exports"
    for f in sorted(exports.iterdir()):
        size = f.stat().st_size
        print(f"  {f.name} ({size:,} bytes)")


if __name__ == "__main__":
    main()
