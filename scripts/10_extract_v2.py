#!/usr/bin/env python3
"""Phase 1: Re-run LLM extraction with the new v2 prompt (tiered classification)."""

import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compass_collector.database import init_db, get_session
from compass_collector.models.document import Document
from compass_collector.extraction_llm.llm_extractor import LLMExtractor

init_db()
session = get_session()

api_key = os.environ.get("DEEPSEEK_API_KEY")
if not api_key:
    print("ERROR: Set DEEPSEEK_API_KEY")
    sys.exit(1)

extractor = LLMExtractor(api_key=api_key)

docs = session.query(Document).filter(Document.url.startswith("http"), Document.cleaned_text != "").all()
doc_list = []
for d in docs:
    text = d.cleaned_text or ""
    if len(text.strip()) < 100:
        text = d.title or ""
    if len(text.strip()) < 100:
        continue
    doc_list.append({"id": d.id, "title": d.title or "", "url": d.url or "", "text": text})

print(f"Loaded {len(doc_list)} documents with text")

output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "extraction")
os.makedirs(output_dir, exist_ok=True)
output_path = os.path.join(output_dir, "extraction_v2.jsonl")

# Resume check
extracted_ids = set()
if os.path.exists(output_path):
    with open(output_path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    d = json.loads(line)
                    extracted_ids.add(d["document_id"])
                except:
                    pass
    print(f"Found {len(extracted_ids)} already extracted")

remaining = [d for d in doc_list if d["id"] not in extracted_ids]
print(f"Remaining: {len(remaining)}")

t0 = time.time()
total_done = len(extracted_ids)
for i, doc in enumerate(remaining):
    text = doc.get("text", "")
    if not text or len(text.strip()) < 100:
        text = doc.get("title", "")
    if not text or len(text.strip()) < 100:
        result = {"has_intervention": False, "extraction_notes": "Insufficient text"}
    else:
        result = extractor.extract(text, doc.get("title"), doc.get("url"))

    e_result = {"document_id": doc["id"], "title": doc["title"][:100], "url": doc["url"], "extraction": result}
    with open(output_path, "a") as f:
        f.write(json.dumps(e_result) + "\n")
        f.flush()

    total_done += 1
    if total_done % 25 == 0:
        elapsed = time.time() - t0
        rate = total_done / elapsed * 60 if elapsed > 0 else 0
        print(f"  {total_done}/{len(doc_list)} ({total_done/len(doc_list)*100:.0f}%) — {rate:.0f} docs/min — cost: ${extractor.stats['total_cost']:.4f}")

elapsed = time.time() - t0
print(f"\nDone! {total_done} in {elapsed/60:.1f} min, cost ${extractor.stats['total_cost']:.4f}, errors {extractor.stats['errors']}")
print(f"Results: {output_path}")
