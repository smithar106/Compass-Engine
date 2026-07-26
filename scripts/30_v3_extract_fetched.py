#!/usr/bin/env python3
"""V3: Extract from V3-fetched case studies only.

Processes documents in data/v3_fetched/ using the V3 LLM prompt.
Separate from 23_v3_extract.py which processes ALL DB documents.
"""

import sys, os, json, time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts._v3_llm import V3Extractor


def main():
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("ERROR: Set DEEPSEEK_API_KEY")
        sys.exit(1)

    extractor = V3Extractor(api_key=api_key)

    fetched_dir = Path(__file__).resolve().parent.parent / "data" / "v3_fetched"
    if not fetched_dir.exists():
        print(f"ERROR: {fetched_dir} not found. Run 24_v3_fetch.py first.")
        sys.exit(1)

    doc_files = list(fetched_dir.glob("*.json"))
    print(f"Found {len(doc_files)} fetched documents")

    output_dir = Path(__file__).resolve().parent.parent / "data" / "extraction"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "extraction_v3.jsonl"

    # Resume check
    extracted_ids = set()
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
        print(f"Found {len(extracted_ids)} already extracted")

    # Stats tracking
    tier_counts = {"tier1": 0, "tier2": 0, "tier3": 0, "rejected": 0, "unknown": 0}
    t0 = time.time()

    for i, fpath in enumerate(doc_files):
        with open(fpath) as f:
            doc = json.load(f)

        doc_id = doc.get("id", "")
        if doc_id in extracted_ids:
            continue

        title = doc.get("title", "")
        url = doc.get("url", "")
        text = doc.get("cleaned_text", doc.get("text", ""))

        if not text or len(text.strip()) < 100:
            result = {"evidence_tier": "rejected", "rejection_reason": "Insufficient source text", "document_type": "insufficient_content"}
        else:
            result = extractor.extract(text, title, url)

        tier = result.get("evidence_tier", "unknown")
        if tier in tier_counts:
            tier_counts[tier] += 1

        e_result = {
            "document_id": doc_id,
            "title": title[:100],
            "url": url,
            "extraction": result,
            "extraction_version": "v3",
        }

        with open(output_path, "a") as f:
            f.write(json.dumps(e_result) + "\n")
            f.flush()

        if (i + 1) % 20 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed * 60 if elapsed > 0 else 0
            print(f"  {i+1}/{len(doc_files)} ({elapsed/60:.1f} min, {rate:.0f}/min) — T1:{tier_counts['tier1']} T2:{tier_counts['tier2']} T3:{tier_counts['tier3']} R:{tier_counts['rejected']} — cost: ${extractor.stats['total_cost']:.4f}")

    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"V3 Extraction Complete!")
    print(f"  Time:      {elapsed/60:.1f} min")
    print(f"  Cost:      ${extractor.stats['total_cost']:.4f}")
    print(f"  Errors:    {extractor.stats['errors']}")
    print(f"  Documents: {len(doc_files)}")
    print(f"  Tier 1:    {tier_counts['tier1']}")
    print(f"  Tier 2:    {tier_counts['tier2']}")
    print(f"  Tier 3:    {tier_counts['tier3']}")
    print(f"  Rejected:  {tier_counts['rejected']}")
    print(f"  Output:    {output_path}")


if __name__ == "__main__":
    main()
