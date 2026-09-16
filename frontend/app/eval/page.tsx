import { EvalDashboardClient } from "@/app/eval/EvalDashboardClient";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { type CompareMatrix, type MlflowRun, type RunSummary } from "@/lib/types";

export const dynamic = "force-dynamic";

const API_BASE = process.env.API_BASE ?? "http://localhost:8000";

async function fetchJson<T>(path: string, fallback: T): Promise<T> {
  try {
    const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
    if (!res.ok) return fallback;
    return (await res.json()) as T;
  } catch {
    return fallback;
  }
}

const HEADLINE = [
  "citation_validity",
  "context_hit_rate",
  "mrr",
  "refusal_correct",
  "numeric_exactness",
  "fiscal_period_correctness",
];

export default async function EvalPage() {
  const runs = await fetchJson<RunSummary[]>("/api/eval/runs?limit=50", []);
  const matrix = await fetchJson<CompareMatrix>(
    `/api/eval/compare?metrics=${HEADLINE.join(",")}`,
    { metrics: [], configs: {} },
  );
  const mlflowRuns = await fetchJson<MlflowRun[]>("/api/eval/mlflow/runs?limit=50", []);

  if (!runs || runs.length === 0) {
    return (
      <Card className="border-border/60">
        <CardHeader>
          <CardTitle>No evaluation runs yet</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="max-w-prose text-sm text-muted-foreground">
            Once the harness runs, this page shows the latest scores against
            their gate thresholds, the trend across runs, and the ablation
            matrix comparing retrieval configurations.
          </p>
          <pre className="overflow-x-auto rounded-lg border border-border/60 bg-card p-4 font-mono text-xs text-muted-foreground">
{`cd backend
python -m apps.evaluator.cli --golden-set evals/golden_set_local.yaml run \\
  --config hybrid_rrf`}
          </pre>
        </CardContent>
      </Card>
    );
  }

  return <EvalDashboardClient runs={runs} matrix={matrix} mlflowRuns={mlflowRuns} />;
}

