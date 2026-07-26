#!/usr/bin/env python3
"""V3: Run LLM extraction with the V3 prompt (tier3 != rejected, full extraction for all tiers)."""

import sys, os, json, time, hashlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compass_collector.database import init_db, get_session
from compass_collector.models.document import Document
from scripts._v3_llm import V3Extractor

def main():
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("ERROR: Set DEEPSEEK_API_KEY")
        sys.exit(1)

    extractor = V3Extractor(api_key=api_key)

    init_db()
    session = get_session()
    docs = session.query(Document).filter(
        Document.url.startswith("http"),
        Document.cleaned_text != "",
        Document.crawl_status == "success"
    ).all()
    session.close()

    doc_list = []
    for d in docs:
        text = d.cleaned_text or ""
        if len(text.strip()) < 100:
            text = d.title or ""
        if len(text.strip()) < 100:
            continue
        doc_list.append({"id": d.id, "title": d.title or "", "url": d.url or "", "text": text})

    print(f"Loaded {len(doc_list)} documents for V3 extraction")

    output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "extraction")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "extraction_v3.jsonl")

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
            result = {"evidence_tier": "rejected", "rejection_reason": "Insufficient source text (<100 chars)", "document_type": "insufficient_content"}
        else:
            result = extractor.extract(text, doc.get("title"), doc.get("url"))

        e_result = {"document_id": doc["id"], "title": doc["title"][:100], "url": doc["url"], "extraction": result, "extraction_version": "v3"}
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

if __name__ == "__main__":
    main()
