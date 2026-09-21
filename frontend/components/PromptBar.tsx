"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  ArrowUp,
  Check,
  ChevronDown,
  Database,
  Lightbulb,
  Mic,
  Plus,
  Scale,
  Square,
  Upload,
  Zap,
  type LucideIcon,
} from "lucide-react";
import type { IndexedDocument } from "@/lib/types";

export type Mode = "Fast" | "Balanced" | "Thorough";

export const MODES: Record<Mode, { icon: LucideIcon; configId: string; hint: string }> = {
  Fast: { icon: Zap, configId: "bm25_only", hint: "Keyword search only" },
  Balanced: { icon: Scale, configId: "hybrid_rrf", hint: "Keyword + vector, fused" },
  Thorough: { icon: Lightbulb, configId: "hybrid_semantic", hint: "Hybrid + semantic ranker" },
};

type PanelId = "add" | "scope" | "mode" | null;

interface SpeechResult {
  results: ArrayLike<ArrayLike<{ transcript: string }>>;
}
interface Recognizer {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((e: SpeechResult) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
  start: () => void;
  stop: () => void;
}

export interface PromptBarProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (value: string) => void;
  onStop?: () => void;
  busy?: boolean;
  documents: IndexedDocument[];
  scope: string[];
  onScopeChange: (next: string[]) => void;
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  placeholder?: string;
  className?: string;
}

export default function PromptBar({
  value,
  onChange,
  onSubmit,
  onStop,
  busy = false,
  documents,
  scope,
  onScopeChange,
  mode,
  onModeChange,
  placeholder = "Ask about revenue, margins, segments, balance sheet…",
  className,
}: PromptBarProps) {
  const [openPanel, setOpenPanel] = useState<PanelId>(null);
  const [recording, setRecording] = useState(false);
  const [canDictate, setCanDictate] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const recognizer = useRef<Recognizer | null>(null);

  useEffect(() => {
    const w = window as unknown as Record<string, unknown>;
    setCanDictate(Boolean(w.SpeechRecognition || w.webkitSpeechRecognition));
  }, []);

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpenPanel(null);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpenPanel(null);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, []);

  useEffect(() => {
    const el = textRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  useEffect(() => () => recognizer.current?.stop(), []);

  const toggle = (id: PanelId) => setOpenPanel((cur) => (cur === id ? null : id));

  function submit() {
    if (busy || !value.trim()) return;
    setOpenPanel(null);
    onSubmit(value.trim());
  }

  function toggleDictation() {
    if (recording) {
      recognizer.current?.stop();
      return;
    }
    const w = window as unknown as Record<string, new () => Recognizer>;
    const Ctor = w.SpeechRecognition || w.webkitSpeechRecognition;
    if (!Ctor) return;
    const base = value.trim();
    const rec = new Ctor();
    rec.continuous = false;
    rec.interimResults = true;
    rec.lang = "en-US";
    rec.onresult = (e) => {
      const said = Array.from(e.results)
        .map((r) => r[0].transcript)
        .join("");
      onChange(base ? `${base} ${said}` : said);
    };
    rec.onend = () => setRecording(false);
    rec.onerror = () => setRecording(false);
    recognizer.current = rec;
    rec.start();
    setRecording(true);
  }

  function toggleDoc(id: string) {
    onScopeChange(scope.includes(id) ? scope.filter((d) => d !== id) : [...scope, id]);
  }

  const ModeIcon = MODES[mode].icon;
  const iconBtn =
    "flex h-9 w-9 items-center justify-center rounded-full text-foreground transition-colors hover:bg-foreground/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

  return (
    <div
      ref={rootRef}
      className={["prompt-bar-glow relative w-full rounded-[24px] bg-muted p-[2px]", className ?? ""].join(" ")}
    >
      <style>{`
        @property --pb-angle {
          syntax: '<angle>';
          inherits: false;
          initial-value: 0deg;
        }
        .prompt-bar-glow {
          --pb-angle: 0deg;
          background-image:
            conic-gradient(from var(--pb-angle),
              transparent 0deg, transparent 295deg,
              #1a1a1a 308deg, #ffffff 325deg, #1a1a1a 342deg,
              transparent 355deg, transparent 360deg);
          animation: pb-rotate 7s linear infinite;
        }
        @keyframes pb-rotate {
          to { --pb-angle: 360deg; }
        }
        @keyframes pb-mic-pulse {
          0% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.5); }
          100% { box-shadow: 0 0 0 10px rgba(239, 68, 68, 0); }
        }
        @media (prefers-reduced-motion: reduce) {
          .prompt-bar-glow { animation: none; }
        }
      `}</style>

      <div className="rounded-[22px] bg-muted p-5 pb-4">
        <textarea
          ref={textRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder={placeholder}
          rows={1}
          aria-label="Ask a question about the filings"
          className="mb-6 w-full resize-none bg-transparent text-base text-foreground placeholder:text-muted-foreground focus:outline-none"
        />

        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1">
            <div className="relative">
              <button
                type="button"
                aria-label="Add a document"
                aria-expanded={openPanel === "add"}
                onClick={() => toggle("add")}
                className={iconBtn}
              >
                <Plus size={20} />
              </button>
              {openPanel === "add" && (
                <div className="absolute left-0 top-11 z-10 min-w-[210px] rounded-2xl bg-popover p-1.5 shadow-lg ring-1 ring-border">
                  <Link
                    href="/corpus"
                    className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left text-sm text-popover-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
                  >
                    <Upload size={16} />
                    Upload a filing
                  </Link>
                </div>
              )}
            </div>

            <div className="relative">
              <button
                type="button"
                aria-label="Choose which documents to search"
                aria-expanded={openPanel === "scope"}
                onClick={() => toggle("scope")}
                className={`${iconBtn} relative`}
              >
                <Database size={18} />
                {scope.length > 0 && (
                  <span className="absolute -right-0.5 -top-0.5 grid size-4 place-items-center rounded-full bg-primary text-[10px] font-semibold text-primary-foreground">
                    {scope.length}
                  </span>
                )}
              </button>
              {openPanel === "scope" && (
                <div className="absolute left-0 top-11 z-10 max-h-72 min-w-[260px] overflow-y-auto rounded-2xl bg-popover p-1.5 shadow-lg ring-1 ring-border">
                  <p className="px-3 pb-1 pt-1.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                    Search in
                  </p>
                  <MenuItem
                    label={`All documents (${documents.length})`}
                    selected={scope.length === 0}
                    onClick={() => onScopeChange([])}
                  />
                  {documents.map((d) => (
                    <MenuItem
                      key={d.doc_id}
                      label={d.doc_id}
                      meta={String(d.chunk_count)}
                      mono
                      selected={scope.includes(d.doc_id)}
                      onClick={() => toggleDoc(d.doc_id)}
                    />
                  ))}
                  {documents.length === 0 && (
                    <p className="px-3 py-2 text-xs text-muted-foreground">No documents indexed yet.</p>
                  )}
                </div>
              )}
            </div>
          </div>

          <div className="flex items-center gap-1">
            <div className="relative">
              <button
                type="button"
                aria-haspopup="listbox"
                aria-expanded={openPanel === "mode"}
                onClick={() => toggle("mode")}
                className="mx-1 flex items-center gap-1 rounded-full bg-secondary px-3 py-1.5 text-sm text-secondary-foreground transition-colors hover:bg-secondary/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <ModeIcon size={14} />
                {mode}
                <ChevronDown size={15} />
              </button>
              {openPanel === "mode" && (
                <div
                  role="listbox"
                  className="absolute right-0 top-11 z-10 min-w-[230px] rounded-2xl bg-popover p-1.5 shadow-lg ring-1 ring-border"
                >
                  {(Object.keys(MODES) as Mode[]).map((m) => (
                    <MenuItem
                      key={m}
                      icon={MODES[m].icon}
                      label={m}
                      meta={MODES[m].hint}
                      selected={m === mode}
                      onClick={() => {
                        onModeChange(m);
                        setOpenPanel(null);
                      }}
                    />
                  ))}
                </div>
              )}
            </div>

            {canDictate && (
              <button
                type="button"
                aria-label={recording ? "Stop dictation" : "Dictate a question"}
                aria-pressed={recording}
                onClick={toggleDictation}
                className={[
                  "flex h-9 w-9 items-center justify-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  recording
                    ? "bg-destructive/10 text-destructive [animation:pb-mic-pulse_1.2s_ease-out_infinite]"
                    : "text-foreground hover:bg-foreground/10",
                ].join(" ")}
              >
                <Mic size={18} />
              </button>
            )}

            {busy ? (
              <button
                type="button"
                aria-label="Stop"
                onClick={onStop}
                className="flex h-9 w-9 items-center justify-center rounded-full bg-foreground/15 text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <Square size={14} fill="currentColor" />
              </button>
            ) : (
              <button
                type="button"
                aria-label="Ask"
                disabled={!value.trim()}
                onClick={submit}
                className="flex h-9 w-9 items-center justify-center rounded-full bg-primary text-primary-foreground transition-opacity focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:bg-foreground/15 disabled:text-foreground/50"
              >
                <ArrowUp size={16} />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function MenuItem({
  icon: Icon,
  label,
  meta,
  mono,
  onClick,
  selected,
}: {
  icon?: LucideIcon;
  label: string;
  meta?: string;
  mono?: boolean;
  onClick: () => void;
  selected?: boolean;
}) {
  return (
    <button
      type="button"
      role="option"
      aria-selected={selected}
      onClick={onClick}
      className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left text-sm text-popover-foreground transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {Icon && <Icon size={16} className="shrink-0" />}
      <span className={`min-w-0 flex-1 truncate ${mono ? "font-mono text-xs" : ""}`}>{label}</span>
      {meta && <span className="shrink-0 text-[11px] text-muted-foreground">{meta}</span>}
      {selected && <Check size={14} className="shrink-0 text-primary" />}
    </button>
  );
}
