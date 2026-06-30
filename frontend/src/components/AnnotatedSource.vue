<script setup lang="ts">
import { computed } from 'vue';
import type { DetectionResult } from 'src/types/detection';

// Read-only annotated rendering of an analyzed text: the same inline <mark>
// highlighting used by the workbench source panel, reusable on the shared page.
const props = defineProps<{
  result: DetectionResult;
  text: string;
}>();

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/\n/g, '<br>');
}

type SpanItem = { start: number; end: number; type: string; severity: string; reason: string };
type EvEvent = { pos: number; kind: 'open' | 'close'; span: SpanItem };
type SafeSeverity = 'low' | 'medium' | 'high';

function safeSeverity(value: unknown): SafeSeverity {
  return value === 'low' || value === 'medium' || value === 'high' ? value : 'medium';
}

function safeSpan(raw: SpanItem, textLength: number): SpanItem | null {
  if (!Number.isInteger(raw.start) || !Number.isInteger(raw.end)) return null;
  if (raw.start < 0 || raw.end <= raw.start || raw.end > textLength) return null;
  return {
    start: raw.start,
    end: raw.end,
    type: raw.type === 'sentence_ai' ? 'sentence_ai' : 'pattern',
    severity: safeSeverity(raw.severity),
    reason: typeof raw.reason === 'string' ? raw.reason : '',
  };
}

const annotatedHtml = computed(() => {
  const src = props.text;
  const spans = (props.result.evidence?.spans ?? [])
    .map((s) => safeSpan(s, src.length))
    .filter((s): s is SpanItem => s !== null);
  if (!src || spans.length === 0) return '';

  const events: EvEvent[] = [];
  for (const s of spans) {
    events.push({ pos: s.start, kind: 'open', span: s });
    events.push({ pos: s.end, kind: 'close', span: s });
  }
  events.sort((a, b) => {
    if (a.pos !== b.pos) return a.pos - b.pos;
    if (a.kind !== b.kind) return a.kind === 'close' ? -1 : 1;
    if (a.kind === 'open') return b.span.end - a.span.end;
    return a.span.end - b.span.end;
  });

  const cls = (s: SpanItem): string => {
    if (s.type === 'sentence_ai') return `span sent-flag sent-flag-${s.severity}`;
    return `span span-${s.severity}`;
  };

  let cursor = 0;
  let out = '';
  for (const ev of events) {
    if (ev.pos > cursor) {
      out += escapeHtml(src.slice(cursor, ev.pos));
      cursor = ev.pos;
    }
    if (ev.kind === 'open') {
      out += `<mark class="${cls(ev.span)}" title="${escapeHtml(ev.span.reason)}">`;
    } else {
      out += '</mark>';
    }
  }
  if (cursor < src.length) out += escapeHtml(src.slice(cursor));
  return out;
});

const sourcePreview = computed(() => annotatedHtml.value || escapeHtml(props.text));
const noSpans = computed(() => (props.result.evidence?.spans?.length ?? 0) === 0);
</script>

<template>
  <div class="source-annotated">
    <div class="annotated-body" v-html="sourcePreview"></div>
    <div v-if="noSpans" class="annotated-note eyebrow">no inline patterns flagged</div>
  </div>
</template>

<style scoped lang="scss">
.source-annotated {
  background: #ffffff;
  border: 1px solid var(--field-border);
  border-radius: 6px;
  padding: 16px 18px;
  height: var(--source-height, clamp(360px, calc(100vh - 260px), 760px));
  overflow-y: auto;

  &::-webkit-scrollbar {
    width: 8px;
  }
  &::-webkit-scrollbar-thumb {
    background: var(--rule-strong);
    border-radius: 4px;
  }
  &::-webkit-scrollbar-track {
    background: transparent;
  }
}
.annotated-body {
  font-family: var(--font-mono);
  font-size: 13px;
  line-height: 1.7;
  color: var(--ink);
  white-space: pre-wrap;
  word-wrap: break-word;
  overflow-wrap: anywhere;
  max-width: 100%;
}
.annotated-body :deep(mark.span) {
  display: inline;
  white-space: normal;
  overflow-wrap: anywhere;
}
.annotated-note {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--rule);
  color: var(--ink-mute);
}
</style>
