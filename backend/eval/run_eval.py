"""
MSAJCE RAG Evaluation Harness (Req 5)
Computes Recall@6, Answer EM, and Answer F1 against ground-truth dataset.

Usage:
  python eval/run_eval.py [--dataset FILE] [--output FILE]
                          [--bypass-cache] [--pipeline-variant TAG]
                          [--api-url URL]
"""
import argparse, json, time, datetime, sys, os
from pathlib import Path


def compute_f1(prediction: str, ground_truth: str) -> float:
    """Token-level F1 between prediction and ground_truth."""
    pred_tokens = prediction.lower().split()
    gt_tokens   = ground_truth.lower().split()
    common = set(pred_tokens) & set(gt_tokens)
    if not common:
        return 0.0
    precision = len(common) / len(pred_tokens)
    recall    = len(common) / len(gt_tokens)
    return 2 * precision * recall / (precision + recall)


def compute_em(prediction: str, ground_truth: str) -> int:
    """Exact match (case-insensitive, whitespace-normalized)."""
    p = " ".join(prediction.lower().split())
    g = " ".join(ground_truth.lower().split())
    return int(p == g)


def run_question(api_url: str, question: str, bypass_cache: bool) -> dict:
    """Call /api/chat and return the response dict."""
    import requests as req
    payload = {"message": question, "session_id": "00000000-0000-0000-0000-000000000001", "bypass_cache": bypass_cache}
    t0 = time.monotonic()
    r = req.post(f"{api_url}/api/chat", json=payload, timeout=60)
    latency_ms = int((time.monotonic() - t0) * 1000)
    r.raise_for_status()
    data = r.json()
    data["_latency_ms"] = latency_ms
    return data


def main():
    parser = argparse.ArgumentParser(description="MSAJCE RAG Evaluation Harness")
    parser.add_argument("--dataset",          default="eval/eval_dataset.json")
    parser.add_argument("--output",           default=None)
    parser.add_argument("--bypass-cache",     action="store_true")
    parser.add_argument("--pipeline-variant", default="default")
    parser.add_argument("--api-url",          default="http://localhost:8000")
    args = parser.parse_args()

    # Load dataset
    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"[ERROR] Dataset not found: {dataset_path}", file=sys.stderr)
        sys.exit(1)

    with open(dataset_path) as f:
        dataset = json.load(f)

    print(f"\n{'='*44}")
    print(f"  MSAJCE RAG Evaluation")
    print(f"  Dataset:  {len(dataset)} questions")
    print(f"  Variant:  {args.pipeline_variant}")
    print(f"  API:      {args.api_url}")
    print(f"  Cache:    {'bypass' if args.bypass_cache else 'enabled'}")
    print(f"{'='*44}\n")

    results = []
    errors  = 0

    for i, item in enumerate(dataset, 1):
        question        = item["question"]
        expected_answer = item["expected_answer"]
        category        = item.get("category", "")
        source_file     = item.get("source_file", "")
        has_exact_id    = item.get("has_exact_identifier", False)

        print(f"  [{i:2d}/{len(dataset)}] {question[:70]}...")
        try:
            resp = run_question(args.api_url, question, args.bypass_cache)
            generated = resp.get("answer", "")
            citations  = resp.get("citations", [])
            latency_ms = resp.get("_latency_ms", 0)

            # Recall@6 — check if any citation stem matches any expected source stem
            def get_stems(text: str) -> set:
                stems = set()
                for part in text.split(","):
                    clean = part.strip().lower()
                    base = os.path.splitext(os.path.basename(clean))[0]
                    if base:
                        stems.add(base)
                return stems

            expected_stems = get_stems(source_file)
            cited_stems = set()
            for c in citations:
                s = c.get("source", "")
                cited_stems.update(get_stems(s))

            recall_at_6 = int(bool(expected_stems & cited_stems))

            answer_em  = compute_em(generated, expected_answer)
            answer_f1  = compute_f1(generated, expected_answer)

            results.append({
                "question":          question,
                "expected_answer":   expected_answer,
                "generated_answer":  generated,
                "category":          category,
                "source_file":       source_file,
                "has_exact_identifier": has_exact_id,
                "recall_at_6":       recall_at_6,
                "answer_em":         answer_em,
                "answer_f1":         round(answer_f1, 4),
                "latency_ms":        latency_ms,
            })
            print(f"         Recall@6={recall_at_6}  EM={answer_em}  F1={answer_f1:.2f}  {latency_ms}ms")

        except Exception as e:
            print(f"         [ERROR] {e}")
            errors += 1
            results.append({
                "question": question, "error": str(e),
                "recall_at_6": 0, "answer_em": 0, "answer_f1": 0.0, "latency_ms": 0,
                "has_exact_identifier": has_exact_id,
            })

    # Aggregate metrics
    valid = [r for r in results if "error" not in r]
    exact_id_results = [r for r in valid if r.get("has_exact_identifier")]

    agg = {
        "mean_recall_at_6":       round(sum(r["recall_at_6"] for r in valid) / max(len(valid), 1), 4),
        "mean_answer_em":         round(sum(r["answer_em"]   for r in valid) / max(len(valid), 1), 4),
        "mean_answer_f1":         round(sum(r["answer_f1"]   for r in valid) / max(len(valid), 1), 4),
        "exact_identifier_recall": round(
            sum(r["recall_at_6"] for r in exact_id_results) / max(len(exact_id_results), 1), 4
        ),
        "mean_latency_ms":        int(sum(r["latency_ms"] for r in valid) / max(len(valid), 1)),
        "total_questions":        len(dataset),
        "successful_questions":   len(valid),
        "errors":                 errors,
    }

    # Print summary
    print(f"\n{'='*44}")
    print(f"  Evaluation Results ({len(valid)} questions)")
    print(f"{'='*44}")
    print(f"  Recall@6:          {agg['mean_recall_at_6']*100:.1f}%")
    print(f"  Answer EM:         {agg['mean_answer_em']*100:.1f}%")
    print(f"  Answer F1:         {agg['mean_answer_f1']*100:.1f}%")
    print(f"  Exact ID Recall:   {agg['exact_identifier_recall']*100:.1f}%")
    print(f"  Mean Latency:      {agg['mean_latency_ms']} ms")
    if errors:
        print(f"  Errors:            {errors}")
    print(f"{'='*44}\n")

    # Write output
    timestamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    output_path = Path(args.output) if args.output else Path(f"eval/results_{timestamp}.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_data = {
        "timestamp":        datetime.datetime.utcnow().isoformat() + "Z",
        "pipeline_variant": args.pipeline_variant,
        "bypass_cache":     args.bypass_cache,
        "aggregate":        agg,
        "questions":        results,
    }
    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2)
    print(f"  Results written to: {output_path}\n")


if __name__ == "__main__":
    main()
