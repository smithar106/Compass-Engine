#!/usr/bin/env python3
"""Phase 1: Run LLM extraction only, streaming results to extraction_attempts.jsonl.
Run this with a long timeout. After it completes, run 08_map_to_db.py."""

import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compass_collector.database import init_db, get_session
from compass_collector.models.document import Document
from compass_collector.extraction_llm.orchestrator import ExtractionOrchestrator

init_db()
session = get_session()

api_key = os.environ.get("DEEPSEEK_API_KEY")
if not api_key:
    print("ERROR: Set DEEPSEEK_API_KEY")
    sys.exit(1)

orch = ExtractionOrchestrator()
orch.set_api_key(api_key)

docs = session.query(Document).filter(Document.url.startswith("http")).all()
doc_list = []
for d in docs:
    text = d.cleaned_text or ""
    if len(text.strip()) < 100:
        text = d.title or ""
    if len(text.strip()) < 100:
        continue
    doc_list.append({"id": d.id, "title": d.title or "", "url": d.url or "", "text": text})

print(f"Loaded {len(doc_list)} documents")

relevance_results, counts = orch.run_relevance_filter(doc_list)
print(f"Relevance: High={counts['high_relevance']}, Possible={counts['possible_relevance']}, Not={counts['not_relevant']}")

relevant_ids = {r["record_id"] for r in relevance_results
                if r["classification"] in ("high_relevance", "possible_relevance")}
relevant_docs = [d for d in doc_list if d["id"] in relevant_ids]
print(f"Sending {len(relevant_docs)} to LLM")

# Check if we already have partial results
extracted_ids = set()
output_path = orch.output_dir / "extraction_attempts.jsonl"
if output_path.exists():
    with open(output_path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    d = json.loads(line)
                    extracted_ids.add(d["document_id"])
                except:
                    pass
    print(f"Found {len(extracted_ids)} already extracted docs, will resume")

remaining = [d for d in relevant_docs if d["id"] not in extracted_ids]
print(f"Remaining to extract: {len(remaining)}")

t0 = time.time()
total_processed = len(extracted_ids)
for i, doc in enumerate(remaining):
    text = doc.get("text", "")
    if not text or len(text.strip()) < 100:
        text = doc.get("title", "")
    if not text or len(text.strip()) < 100:
        e_result = {"document_id": doc["id"], "title": doc["title"][:100], "url": doc["url"],
                     "extraction": {"has_intervention": False, "extraction_notes": "Insufficient text"}}
    else:
        result = orch.extractor.extract(text, doc.get("title"), doc.get("url"))
        e_result = {"document_id": doc["id"], "title": doc["title"][:100], "url": doc["url"], "extraction": result}

    with open(output_path, "a") as f:
        f.write(json.dumps(e_result) + "\n")
        f.flush()

    total_processed += 1
    if total_processed % 25 == 0:
        elapsed = time.time() - t0
        rate = total_processed / elapsed * 60 if elapsed > 0 else 0
        cost = orch.extractor.stats['total_cost']
        pct_done = total_processed / len(relevant_docs) * 100
        print(f"  {total_processed}/{len(relevant_docs)} ({pct_done:.0f}%) — {rate:.0f} docs/min — cost: ${cost:.4f}")

elapsed = time.time() - t0
print(f"\nDone! Processed {total_processed} documents in {elapsed/60:.1f} minutes")
print(f"Cost: ${orch.extractor.stats['total_cost']:.4f}")
print(f"Errors: {orch.extractor.stats['errors']}")
print(f"Results in: {output_path}")
