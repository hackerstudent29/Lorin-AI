"""
Automated LLM-as-a-judge Evaluation Pipeline using Ragas.
Scores the RAG pipeline on Faithfulness and Answer Relevancy.
"""
import os, json, argparse, sys
from pathlib import Path
from dotenv import load_dotenv

# Ragas and Langchain imports
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy
from datasets import Dataset
from langchain_openai import ChatOpenAI

load_dotenv()

# We will use NVIDIA's API via the OpenAI SDK wrapper for Ragas
# since Ragas supports Langchain LLMs.
# meta/llama-3.1-8b-instruct or 70b-instruct can act as the judge.

def run_ragas_eval(dataset_path: str):
    print("Loading Ragas evaluation pipeline...")
    
    NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
    if not NVIDIA_API_KEY:
        print("[ERROR] NVIDIA_API_KEY not found in environment.")
        sys.exit(1)

    # Initialize Langchain ChatOpenAI pointing to NVIDIA's NIM API
    judge_llm = ChatOpenAI(
        api_key=NVIDIA_API_KEY,
        base_url="https://integrate.api.nvidia.com/v1",
        model="meta/llama-3.1-70b-instruct",
        temperature=0.1
    )

    # Read the dataset we want to evaluate
    p = Path(dataset_path)
    if not p.exists():
        print(f"[ERROR] Dataset {dataset_path} not found.")
        sys.exit(1)

    with open(p, "r") as f:
        raw_data = json.load(f)

    # Ragas requires a HuggingFace Dataset object with keys:
    # question, answer, contexts, ground_truth
    
    questions = []
    answers = []
    contexts = []
    ground_truths = []
    
    print(f"Preparing {len(raw_data)} questions for evaluation...")
    import requests
    
    # Generate answers from our live API
    API_URL = "http://localhost:8000/api/chat"
    
    for i, item in enumerate(raw_data, 1):
        q = item["question"]
        gt = item["expected_answer"]
        print(f"  [{i}/{len(raw_data)}] Evaluating: {q[:50]}...")
        
        try:
            # We don't stream for eval, just grab the full answer
            resp = requests.post(API_URL, json={"message": q, "bypass_cache": True})
            resp.raise_for_status()
            data = resp.json()
            
            ans = data.get("answer", "")
            # citations represent our retrieved contexts
            cits = data.get("citations", [])
            # Ideally we'd store the raw chunk text, but for this demo we'll use citation sources
            # To do proper Ragas, you need the actual context string. Let's fetch it via a mock or assume it.
            # Ragas faithfulness needs actual text. If we don't have it in the API response,
            # we can pass the citation strings as a proxy context for now.
            ctxs = [c["source"] + (" - " + c["section"] if c.get("section") else "") for c in cits]
            if not ctxs:
                ctxs = ["No context retrieved."]
                
            questions.append(q)
            answers.append(ans)
            contexts.append(ctxs)
            ground_truths.append(gt)
            
        except Exception as e:
            print(f"  [ERROR] {e}")
            
    eval_dataset = Dataset.from_dict({
        "question": questions,
        "answer": answers,
        "contexts": contexts,
        "ground_truth": ground_truths
    })
    
    print("Running LLM-as-a-judge scoring. This may take a moment...")
    
    # We evaluate Faithfulness (No hallucinations) and Answer Relevancy (Directly answers the prompt)
    # We pass the custom NVIDIA LLM to both the llm and embeddings if needed.
    # Note: Ragas metrics might require an embedding model. We can use ChatOpenAI for the LLM.
    
    metrics = [faithfulness, answer_relevancy]
    
    try:
        results = evaluate(
            eval_dataset,
            metrics=metrics,
            llm=judge_llm
        )
        print("\\n=== RAGAS EVALUATION RESULTS ===")
        print(results)
        
        # Save results
        out_path = Path("eval/ragas_results.json")
        out_path.parent.mkdir(exist_ok=True)
        # Ragas returns a dataset with scores appended, and a summary dict
        out_data = {
            "summary": results,
            "details": eval_dataset.to_pandas().to_dict(orient="records")
        }
        with open(out_path, "w") as f:
            json.dump(out_data, f, indent=2, default=str)
        print(f"\\nSaved detailed results to {out_path}")
        
    except Exception as e:
        print(f"[ERROR] Ragas evaluation failed: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="eval/eval_dataset.json")
    args = parser.parse_args()
    run_ragas_eval(args.dataset)
