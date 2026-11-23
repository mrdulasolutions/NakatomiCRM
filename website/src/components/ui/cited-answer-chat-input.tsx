"use client";

import * as React from "react";
import { ArrowUp, BookOpen, ChevronRight, ExternalLink, Square } from "lucide-react";

export type CitedStatus = "idle" | "reading" | "answering" | "done";

export type CitedSource = {
  id: string;
  title: string;
  domain?: string;
  url?: string;
  /** Progress from 0 to 1. Omit for a completed source. */
  progress?: number;
  tone?: 1 | 2 | 3 | 4 | 5;
};

export type CitedSentence = { text: string; cite?: string[] };

export type CitedAnswerChatInputProps = {
  status?: CitedStatus;
  prompt?: string;
  history?: { prompt: string; answer: string }[];
  sources?: CitedSource[];
  answer?: string | CitedSentence[];
  value?: string;
  defaultValue?: string;
  onValueChange?: (value: string) => void;
  onSubmit?: (value: string) => void;
  onStop?: () => void;
  onSourceClick?: (source: CitedSource) => void;
  activeSource?: string | null;
  onActiveSourceChange?: (id: string | null) => void;
  placeholder?: string;
  followUpPlaceholder?: string;
  answerNote?: string;
  disabled?: boolean;
  className?: string;
  ref?: React.ComponentProps<"div">["ref"];
};

const EMPTY_SOURCES: CitedSource[] = [];
const EASE = "cubic-bezier(0.22, 1, 0.36, 1)";
const TONE_TILE = { 1: "from-chart-1 to-chart-4", 2: "from-chart-2 to-chart-3", 3: "from-chart-3 to-chart-1", 4: "from-chart-4 to-chart-2", 5: "from-chart-5 to-chart-4" } as const;
const TONE_CHIP = { 1: "bg-chart-1/15 ring-chart-1/50", 2: "bg-chart-2/15 ring-chart-2/50", 3: "bg-chart-3/15 ring-chart-3/50", 4: "bg-chart-4/20 ring-chart-4/60", 5: "bg-chart-5/15 ring-chart-5/50" } as const;
const TONE_BAR = { 1: "bg-chart-1", 2: "bg-chart-2", 3: "bg-chart-3", 4: "bg-chart-4", 5: "bg-chart-5" } as const;
const TONE_RING = { 1: "ring-chart-1", 2: "ring-chart-2", 3: "ring-chart-3", 4: "ring-chart-4", 5: "ring-chart-5" } as const;

function toneOf(source: CitedSource, index: number) {
  return source.tone ?? (((index % 5) + 1) as NonNullable<CitedSource["tone"]>);
}

export function CitedAnswerChatInput({
  status = "idle",
  prompt = "",
  history = [],
  sources = EMPTY_SOURCES,
  answer = "",
  value,
  defaultValue = "",
  onValueChange,
  onSubmit,
  onStop,
  onSourceClick,
  activeSource,
  onActiveSourceChange,
  placeholder = "Ask anything",
  followUpPlaceholder = "Ask a follow-up",
  answerNote,
  disabled = false,
  className = "",
  ref,
}: CitedAnswerChatInputProps) {
  const [draft, setDraft] = React.useState(defaultValue);
  const [localActive, setLocalActive] = React.useState<string | null>(null);
  const [expanded, setExpanded] = React.useState(status === "reading");
  const [reduced, setReduced] = React.useState(true);
  const transcript = React.useRef<HTMLDivElement>(null);
  const header = React.useRef<HTMLSpanElement>(null);
  const seen = React.useRef(0);
  const regionId = React.useId();
  const inputValue = value ?? draft;
  const busy = status === "reading" || status === "answering";
  const active = activeSource === undefined ? localActive : activeSource;
  const sentences = Array.isArray(answer) ? answer : answer ? [{ text: answer }] : [];
  const completed = status === "done" ? sentences.map(sentence => sentence.text).join(" ") : "";

  React.useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  React.useEffect(() => {
    if (status === "reading") setExpanded(true);
    if (status === "answering") setExpanded(false);
  }, [status]);

  React.useEffect(() => {
    if (reduced || status !== "reading") return;
    const shimmer = header.current?.animate(
      [{ backgroundPosition: "100% 0" }, { backgroundPosition: "0% 0" }],
      { duration: 1800, iterations: Infinity, easing: "linear" },
    );
    return () => shimmer?.cancel();
  }, [status, reduced]);

  React.useLayoutEffect(() => {
    const box = transcript.current;
    if (!box) {
      seen.current = 0;
      return;
    }
    const rows = Array.from(box.querySelectorAll<HTMLElement>("[data-source]"));
    if (!reduced && status === "reading") {
      rows.slice(seen.current).forEach((row, index) => row.animate(
        [{ opacity: 0, transform: "translateY(8px)" }, { opacity: 1, transform: "translateY(0)" }],
        { duration: 360, delay: index * 60, easing: EASE, fill: "backwards" },
      ));
    }
    seen.current = rows.length;
    box.scrollTop = box.scrollHeight;
  }, [status, sources.length, sentences.length, reduced, history.length]);

  function setActive(id: string | null) {
    if (activeSource === undefined) setLocalActive(id);
    onActiveSourceChange?.(id);
  }

  function changeValue(next: string) {
    if (value === undefined) setDraft(next);
    onValueChange?.(next);
  }

  function submit() {
    const message = inputValue.trim();
    if (!message || busy || disabled || !onSubmit) return;
    onSubmit(message);
    changeValue("");
  }

  function chip(id: string, key: string) {
    const index = sources.findIndex(source => source.id === id);
    const source = sources[index];
    if (!source) return null;
    return (
      <button
        key={key}
        type="button"
        data-cite={id}
        aria-label={`Source ${index + 1}: ${source.title}`}
        onMouseEnter={() => setActive(id)}
        onMouseLeave={() => setActive(null)}
        onFocus={() => setActive(id)}
        onBlur={() => setActive(null)}
        onClick={() => { setExpanded(true); onSourceClick?.(source); }}
        className={`mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-md px-1 align-text-top font-mono text-[11px] font-semibold text-foreground ring-1 transition-transform motion-reduce:transition-none focus-visible:ring-2 focus-visible:ring-ring ${TONE_CHIP[toneOf(source, index)]} ${active === id ? "-translate-y-0.5 ring-2" : ""}`}
      >
        {index + 1}
      </button>
    );
  }

  return (
    <div ref={ref} data-slot="cited-answer-chat-input" data-state={status} data-active-source={active ?? ""} className={`flex h-full min-h-0 w-full max-w-[480px] flex-col text-card-foreground ${className}`}>
      {(status !== "idle" || history.length > 0) && (
        <div ref={transcript} data-transcript role="region" aria-label="Conversation" tabIndex={0} className="mb-4 min-h-0 flex-1 overflow-y-auto overflow-x-hidden px-1 outline-none focus-visible:ring-2 focus-visible:ring-ring">
          {history.map((turn, index) => (
            <div key={index} data-past-turn className="mb-5">
              <p className="ml-auto w-fit max-w-[94%] break-words rounded-2xl rounded-br-sm bg-muted px-3.5 py-2.5 text-[13px] leading-5 text-foreground">{turn.prompt}</p>
              <p className="mt-2 break-words text-sm leading-6 text-foreground">{turn.answer}</p>
            </div>
          ))}
          {status !== "idle" && <>
          <div data-question className="ml-auto w-fit max-w-[94%] rounded-2xl rounded-br-sm bg-muted px-3.5 py-2.5 text-[13px] leading-5 text-foreground">
            <p className="break-words">{prompt}</p>
          </div>
          <div data-assistant className="mt-4 min-w-0">
            {(sources.length > 0 || status === "reading") && (
              <>
                <button
                  type="button"
                  data-sources-toggle
                  aria-expanded={expanded}
                  aria-controls={`${regionId}-sources`}
                  disabled={status === "reading"}
                  onClick={() => setExpanded(!expanded)}
                  className="flex max-w-full items-center gap-2 rounded-full text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-default"
                >
                  <BookOpen className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
                  <span ref={header} data-shimmer className={status === "reading" && !reduced ? "bg-[linear-gradient(90deg,var(--color-muted-foreground)_0%,var(--color-muted-foreground)_42%,var(--color-foreground)_50%,var(--color-muted-foreground)_58%,var(--color-muted-foreground)_100%)] bg-[length:250%_100%] bg-clip-text font-medium text-transparent" : "font-medium text-muted-foreground"}>
                    {status === "reading" ? (sources.length ? "Running workspace tools" : "Working on your request") : `${sources.length} workspace tool ${sources.length === 1 ? "call" : "calls"}`}
                  </span>
                  {status !== "reading" && !expanded && (
                    <span data-source-dots className="ml-1 inline-flex items-center gap-1" aria-hidden="true">
                      {sources.map((source, index) => <span key={source.id} data-dot={source.id} className={`size-2 rounded-full bg-linear-to-br transition-transform motion-reduce:transition-none ${TONE_TILE[toneOf(source, index)]} ${active === source.id ? "scale-150" : ""}`} />)}
                    </span>
                  )}
                  {status !== "reading" && <ChevronRight className={`size-3.5 text-muted-foreground transition-transform motion-reduce:transition-none ${expanded ? "rotate-90" : ""}`} aria-hidden="true" />}
                </button>
                <ul id={`${regionId}-sources`} data-source-list hidden={!expanded} className="mt-3 space-y-2">
                  {sources.map((source, index) => {
                    const tone = toneOf(source, index);
                    const progress = source.progress === undefined ? 1 : Math.min(1, Math.max(0, source.progress));
                    return (
                      <li key={source.id} id={`${regionId}-${source.id}`} data-source={source.id} data-progress={progress.toFixed(2)}>
                        <button
                          type="button"
                          onMouseEnter={() => setActive(source.id)}
                          onMouseLeave={() => setActive(null)}
                          onFocus={() => setActive(source.id)}
                          onBlur={() => setActive(null)}
                          onClick={() => onSourceClick?.(source)}
                          className={`flex w-full items-center gap-3 rounded-xl border border-border/70 bg-card p-2.5 text-left outline-none transition-[transform,box-shadow] motion-reduce:transition-none focus-visible:ring-2 focus-visible:ring-ring ${active === source.id ? `-translate-y-0.5 ring-2 shadow-md ${TONE_RING[tone]}` : ""}`}
                        >
                          <span className={`flex size-8 shrink-0 items-center justify-center rounded-lg bg-linear-to-br text-[11px] font-bold text-background ${TONE_TILE[tone]}`}>{index + 1}</span>
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-xs font-medium text-foreground">{source.title}</span>
                            <span className="mt-1 flex items-center gap-2 text-[11px] text-muted-foreground">
                              <span className="truncate">{source.domain ?? "source"}</span>
                              <span className="h-1 flex-1 overflow-hidden rounded-full bg-muted" aria-hidden="true"><span data-bar className={`block h-full rounded-full ${TONE_BAR[tone]} transition-[width] duration-500 ease-out motion-reduce:transition-none`} style={{ width: `${progress * 100}%` }} /></span>
                              <span className="font-mono tabular-nums">{progress < 1 ? `${Math.round(progress * 100)}%` : "done"}</span>
                            </span>
                          </span>
                          {source.url && <ExternalLink className="size-3 shrink-0 text-muted-foreground" aria-hidden="true" />}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </>
            )}
            {(status === "answering" || status === "done") && (
              <div data-answer role="region" aria-label="Answer" className="mt-4 space-y-2 break-words text-sm leading-6 text-foreground">
                <p>
                  {sentences.map((sentence, index) => (
                    <React.Fragment key={index}>
                      {index > 0 ? " " : ""}
                      {sentence.text}
                      {sentence.cite?.map(id => chip(id, `${index}-${id}`))}
                    </React.Fragment>
                  ))}
                  {status === "answering" && <span data-cursor className="ml-0.5 inline-block h-3.5 w-1 translate-y-0.5 rounded-full bg-primary motion-safe:animate-pulse" />}
                </p>
                {answerNote && status === "done" && <p className="text-xs leading-4 text-muted-foreground">{answerNote}</p>}
              </div>
            )}
          </div>
          </>}
        </div>
      )}
      <form data-composer className="relative mt-auto shrink-0 rounded-3xl border border-border bg-card p-4 shadow-xl shadow-primary/5" onSubmit={event => { event.preventDefault(); submit(); }}>
        <textarea
          aria-label={status === "idle" ? placeholder : followUpPlaceholder}
          placeholder={status === "idle" ? placeholder : followUpPlaceholder}
          value={inputValue}
          disabled={disabled}
          rows={2}
          maxLength={600}
          onChange={event => changeValue(event.target.value)}
          onKeyDown={event => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              submit();
            }
          }}
          className="block min-h-[56px] w-full resize-none rounded-lg bg-transparent p-1 text-[15px] leading-6 tracking-tight text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
        />
        <div className="mt-3 flex items-center justify-between gap-2">
          <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground"><BookOpen className="size-3 shrink-0" aria-hidden="true" />Local CRM tool calls</span>
          {busy && onStop ? (
            <button key="stop" type="button" data-stop aria-label="Stop" onClick={onStop} className="inline-flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground outline-none transition-transform hover:scale-105 active:scale-95 motion-reduce:transform-none motion-reduce:transition-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-card">
              <Square className="size-3.5 fill-current" aria-hidden="true" />
            </button>
          ) : (
            <button key="send" type="submit" data-send aria-label="Send prompt" disabled={disabled || busy || !inputValue.trim() || !onSubmit} className="inline-flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground outline-none transition-transform hover:scale-105 active:scale-95 motion-reduce:transform-none motion-reduce:transition-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-card disabled:scale-100 disabled:bg-muted disabled:text-muted-foreground disabled:opacity-100">
              <ArrowUp className="size-4" strokeWidth={2} aria-hidden="true" />
            </button>
          )}
        </div>
      </form>
      <div className="sr-only" role="status" aria-live="polite" aria-atomic="true" data-announcement>{status === "reading" ? "Working on your request." : completed}</div>
    </div>
  );
}

export default CitedAnswerChatInput;
