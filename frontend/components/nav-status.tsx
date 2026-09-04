"use client";

import { useEffect, useState } from "react";

interface StatusData {
  search_backend?: string;
  default_config_id?: string;
  enable_semantic_ranker?: boolean;
  enable_embeddings?: boolean;
  llm_provider?: string;
}

export function NavStatus() {
  const [status, setStatus] = useState<StatusData | null>(null);

  useEffect(() => {
    fetch("/api/status")
      .then((res) => res.json())
      .then((data) => setStatus(data))
      .catch(() => setStatus({ search_backend: "azure", default_config_id: "hybrid_semantic" }));
  }, []);

  const backend = status?.search_backend || "azure";
  const ranker = status?.enable_semantic_ranker ? " + semantic ranker" : "";
  const config = status?.default_config_id
    ? status.default_config_id.replace("_", " ")
    : "hybrid";

  return (
    <div className="ml-auto flex items-center gap-2">
      <span className="hidden font-mono text-[11px] text-muted-foreground sm:inline">
        {backend} · {config}{ranker}
      </span>
      <span
        className="size-1.5 rounded-full bg-primary shadow-[0_0_8px_var(--primary)]"
        title={`Backend: ${backend}`}
      />
    </div>
  );
}
