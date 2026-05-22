<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useDetectionStore } from 'src/stores/detection';
import { useRewriteStore } from 'src/stores/rewrite';
import type { Mode, Severity, Verdict } from 'src/types/detection';
import type { VoicePreset } from 'src/types/rewrite';
import type { QInput } from 'quasar';

const route = useRoute();
const router = useRouter();
const detectStore = useDetectionStore();
const rewriteStore = useRewriteStore();

const MAX_CHARS = 50_000;
const text = ref('');
const sourceInputRef = ref<InstanceType<typeof QInput> | null>(null);
const isEditing = ref(false);

const activeTab = ref<'detect' | 'rewrite'>(
  route.path.endsWith('/rewrite') || route.query.tab === 'rewrite' ? 'rewrite' : 'detect',
);
watch(activeTab, (t) => {
  router.replace({ query: { ...route.query, tab: t } });
});

// ===== detector =====
const detectMode = ref<Mode>('balanced');
const modeOptions = [
  { label: 'Fast', value: 'fast' },
  { label: 'Balanced', value: 'balanced' },
  { label: 'Thorough', value: 'thorough' },
];
const canDetect = computed(() => text.value.trim().length > 0 && !detectStore.loading);
async function handleDetect() {
  if (!canDetect.value) return;
  await detectStore.detect(text.value, detectMode.value);
}

function verdictLabel(v: Verdict): string {
  return { human: 'Human', likely_human: 'Likely human', uncertain: 'Uncertain', likely_ai: 'Likely AI', ai: 'AI' }[v];
}
function severityClass(s: Severity): string {
  return `sev-bg-${s}`;
}
function aiClass(p: number): string {
  if (p < 0.30) return 'sev-bg-low';
  if (p < 0.65) return 'sev-bg-medium';
  return 'sev-bg-high';
}
function pct(p: number | undefined | null): string {
  if (p === null || p === undefined || Number.isNaN(p)) return '—';
  return `${Math.round(p * 100)}%`;
}
function num(n: number | null | undefined, d = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return n.toFixed(d);
}

// Gauge shows HUMAN-likeness (inverse of AI probability): full arc = 100% human.
const gaugePercent = computed(() =>
  detectStore.result ? Math.round(detectStore.result.result.human_probability * 100) : 0,
);
const gaugeStrokeColor = computed(() => {
  const human = detectStore.result?.result.human_probability ?? 0;
  if (human >= 0.70) return 'var(--accent-3)'; // sage — clearly human
  if (human >= 0.35) return 'var(--accent-2)'; // coral — uncertain
  return 'var(--accent)';                       // indigo — likely AI
});
const arcDashOffset = computed(() => {
  // semi-circle gauge: 180deg = π·r ≈ 502 (r=160)
  const total = Math.PI * 160;
  return total - (total * gaugePercent.value) / 100;
});

const statContrib = computed(() => detectStore.result?.signals?.statistical?.contributors);
const matches = computed(() => detectStore.result?.signals?.patterns?.matches ?? []);

const annotatedHtml = computed(() => {
  const r = detectStore.result;
  if (!r) return '';
  const spans = r.evidence?.spans ?? [];
  const src = text.value;
  if (!src || spans.length === 0) return '';

  // Build an event stream so nested spans (e.g. a phrase underline inside a
  // sentence-level background) render correctly. At each boundary we close
  // any spans that end here, open any that start here, prefixing the longer
  // span first so inner spans nest inside outer ones.
  type SpanItem = { start: number; end: number; type: string; severity: string; reason: string };
  type Event = { pos: number; kind: 'open' | 'close'; span: SpanItem };
  const events: Event[] = [];
  for (const s of spans) {
    events.push({ pos: s.start, kind: 'open', span: s });
    events.push({ pos: s.end, kind: 'close', span: s });
  }
  events.sort((a, b) => {
    if (a.pos !== b.pos) return a.pos - b.pos;
    if (a.kind !== b.kind) return a.kind === 'close' ? -1 : 1;
    // same position, both open: outer (longer) span opens first
    if (a.kind === 'open') return b.span.end - a.span.end;
    // both close: inner (shorter) span closes first
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
function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/\n/g, '<br>');
}

const sortedSentences = computed(() => {
  const ss = detectStore.result?.signals?.llm_judge?.sentence_scores ?? [];
  return [...ss].sort((a, b) => b.score - a.score);
});
const rubricEntries = computed(() => {
  const rs = detectStore.result?.rubric_scores;
  if (!rs) return [];
  return Object.entries(rs).map(([id, v]) => ({ id, score: v.score, evidence: v.evidence }));
});
function rubricBarColor(score: number): string {
  if (score >= 0.7) return 'var(--accent-3)';
  if (score >= 0.4) return 'var(--accent-2)';
  return 'var(--accent)';
}

// ===== rewriter =====
const rewriteMode = ref<Mode>('balanced');
const voice = ref<VoicePreset | null>(null);
const customVoice = ref('');
const targetAi = ref(0.30);
const maxIterations = ref(2);

const voiceOptions = [
  { label: 'Auto — general human', value: null },
  { label: 'Casual tech blog', value: 'casual_tech_blog' },
  { label: 'Personal essay', value: 'personal_essay' },
  { label: 'Business — no buzzwords', value: 'business_minus_buzzwords' },
  { label: 'LinkedIn human', value: 'linkedin_human' },
];

const canRewrite = computed(() => text.value.trim().length > 0 && !rewriteStore.loading);
async function handleRewrite() {
  if (!canRewrite.value) return;
  await rewriteStore.rewrite(
    text.value, rewriteMode.value, voice.value,
    customVoice.value.trim() || null, targetAi.value, maxIterations.value,
  );
}
function copyRewritten() {
  if (rewriteStore.result) void navigator.clipboard.writeText(rewriteStore.result.rewritten_text);
}
function useRewrittenAsInput() {
  if (rewriteStore.result) {
    text.value = rewriteStore.result.rewritten_text;
    rewriteStore.reset();
  }
}
function jumpToRewriter() {
  activeTab.value = 'rewrite';
}
const rewriteDelta = computed(() => {
  if (!rewriteStore.result) return 0;
  return rewriteStore.result.before.ai_probability - rewriteStore.result.after.ai_probability;
});

const sourceHasContent = computed(() => text.value.trim().length > 0);
const sourcePreview = computed(() => {
  if (annotatedHtml.value) return annotatedHtml.value;
  return escapeHtml(text.value);
});

// Show the annotated preview (read-only div with <mark> highlights) when we
// already have analytics for the *current* text and the user is not actively
// editing. A click on the preview switches to the editor; blur switches back.
const showAnnotatedPreview = computed(
  () =>
    sourceHasContent.value
    && detectStore.result !== null
    && text.value === detectStore.lastAnalyzedText
    && !isEditing.value,
);

async function enterEditMode(): Promise<void> {
  isEditing.value = true;
  await nextTick();
  sourceInputRef.value?.focus?.();
}

function exitEditMode(): void {
  isEditing.value = false;
}

function clearSource(): void {
  text.value = '';
  detectStore.reset();
  rewriteStore.reset();
  isEditing.value = false;
}

// Reset analytics ONLY when the source text diverges from what was analysed.
// Toggling between annotated preview and editor must not wipe results.
watch(text, (next) => {
  if (detectStore.result && next !== detectStore.lastAnalyzedText) {
    detectStore.reset();
  }
  if (rewriteStore.result && next !== rewriteStore.result.rewritten_text) {
    // Rewrite result was tied to the previous input — let it linger until the
    // user runs Rewrite again. Don't reset here to keep the diff visible.
  }
});
</script>

<template>
  <q-page class="workbench">
    <div class="wb-grid">
      <!-- ============ LEFT: source (always visible) ============ -->
      <aside class="wb-source">
        <div class="row items-center q-mb-sm">
          <span class="eyebrow">source text</span>
          <span v-if="showAnnotatedPreview" class="eyebrow source-hint">
            · click to edit
          </span>
          <q-space />
          <q-btn
            v-if="sourceHasContent"
            flat dense no-caps size="sm"
            icon="close"
            label="Clear"
            class="clear-btn"
            @click="clearSource"
          >
            <q-tooltip anchor="top middle" self="bottom middle">
              Clear source text and reset results
            </q-tooltip>
          </q-btn>
          <span class="eyebrow mono-count q-ml-md">
            {{ text.length }}<span class="text-grey-5"> / {{ MAX_CHARS }}</span>
          </span>
        </div>

        <!-- Annotated read-only preview. Click anywhere → enter edit mode. -->
        <div
          v-if="showAnnotatedPreview"
          class="source-annotated"
          role="button"
          tabindex="0"
          @click="enterEditMode"
          @keydown.enter.prevent="enterEditMode"
        >
          <div class="annotated-body" v-html="sourcePreview"></div>
          <div
            v-if="(detectStore.result?.evidence?.spans?.length ?? 0) === 0"
            class="annotated-note eyebrow"
          >
            no inline patterns flagged
          </div>
        </div>

        <!-- Editable input. Blur (click outside) returns to annotated preview
             if a result for the current text still exists. Height matches the
             annotated preview exactly so the panel doesn't jump on mode swap. -->
        <q-input
          v-else
          ref="sourceInputRef"
          v-model="text"
          type="textarea"
          outlined
          :maxlength="MAX_CHARS"
          dense
          placeholder="Paste a text once — analyze and rewrite it on the right."
          class="source-input"
          @blur="exitEditMode"
        />
      </aside>

      <!-- ============ RIGHT: workbench (tabs) ============ -->
      <section class="wb-panel">
        <div class="wb-titlebar">
          <h1 class="wb-title h-display">
            Spot the
            <span class="font-display accent">machine</span>,
            keep the
            <span class="font-display accent">voice</span>.
          </h1>
        </div>

        <q-tabs
          v-model="activeTab"
          dense
          class="wb-tabs"
          align="left"
          narrow-indicator
          no-caps
        >
          <q-tab name="detect" label="01 — Detect" />
          <q-tab name="rewrite" label="02 — Rewrite" />
        </q-tabs>

        <div class="editorial-rule q-mb-lg"></div>

        <q-tab-panels v-model="activeTab" animated keep-alive class="bg-transparent" swipeable>

          <!-- ============ DETECT TAB ============ -->
          <q-tab-panel name="detect" class="q-pa-none">
            <div class="row items-center q-gutter-md q-mb-md">
              <span class="eyebrow">analysis mode</span>
              <q-btn-toggle
                v-model="detectMode"
                :options="modeOptions"
                color="grey-3"
                text-color="grey-8"
                toggle-color="primary"
                toggle-text-color="white"
                rounded
                unelevated
                no-caps
                dense
              />
              <q-space />
              <q-btn
                label="Analyze"
                unelevated
                no-caps
                class="bg-primary text-white"
                :loading="detectStore.loading"
                :disable="!canDetect"
                @click="handleDetect"
              >
                <template #loading><q-spinner-dots /></template>
              </q-btn>
            </div>

            <q-banner v-if="detectStore.error" class="bg-red-1 text-red-10 q-mb-md" rounded dense>
              <template #avatar><q-icon name="error_outline" /></template>
              {{ detectStore.error }}
            </q-banner>

            <div v-if="detectStore.loading && !detectStore.result" class="loader">
              <div class="loader-pulse"></div>
              <div class="eyebrow q-mt-md">running detector</div>
            </div>

            <template v-if="detectStore.result">
              <!-- gauge + verdict -->
              <div class="result-hero row items-center">
                <div class="gauge-wrap">
                  <svg viewBox="0 0 360 200" class="gauge-svg">
                    <path d="M 20 180 A 160 160 0 0 1 340 180"
                          fill="none" stroke="var(--rule)" stroke-width="14" stroke-linecap="butt"/>
                    <path d="M 20 180 A 160 160 0 0 1 340 180"
                          fill="none" :stroke="gaugeStrokeColor" stroke-width="14" stroke-linecap="butt"
                          :stroke-dasharray="Math.PI * 160"
                          :stroke-dashoffset="arcDashOffset" />
                  </svg>
                  <div class="gauge-readout">
                    <span class="gauge-num">{{ gaugePercent }}<span class="gauge-pct">%</span></span>
                    <span class="eyebrow q-mt-xs">human score</span>
                  </div>
                </div>
                <div class="hero-summary">
                  <div class="eyebrow">verdict</div>
                  <div class="verdict-line">
                    <span class="font-display verdict-word">
                      {{ verdictLabel(detectStore.result.result.verdict) }}
                    </span>
                  </div>
                  <div class="kv-grid">
                    <div class="kv">
                      <span class="eyebrow">AI</span>
                      <span class="font-mono kv-num">{{ pct(detectStore.result.result.ai_probability) }}</span>
                    </div>
                    <div class="kv">
                      <span class="eyebrow">Human</span>
                      <span class="font-mono kv-num">{{ pct(detectStore.result.result.human_probability) }}</span>
                    </div>
                    <div class="kv">
                      <span class="eyebrow">Confidence</span>
                      <span class="font-mono kv-num">{{ pct(detectStore.result.result.confidence) }}</span>
                    </div>
                    <div class="kv">
                      <span class="eyebrow">Language</span>
                      <span class="font-mono kv-num">{{ detectStore.result.request.language_detected ?? '—' }}</span>
                    </div>
                  </div>
                  <q-btn
                    v-if="detectStore.result.result.ai_probability >= 0.3"
                    flat
                    no-caps
                    icon-right="arrow_forward"
                    label="Rewrite this text"
                    color="primary"
                    class="rewrite-cta q-mt-md"
                    @click="jumpToRewriter"
                  />
                </div>
              </div>

              <div class="editorial-rule q-my-lg"></div>

              <!-- collapsible signal sections -->
              <div class="signal-sections">
                <!-- statistical -->
                <q-expansion-item
                  v-if="detectStore.result.signals?.statistical"
                  expand-icon="expand_more"
                  class="signal-item"
                  header-class="signal-header"
                >
                  <template #header>
                    <div class="row full-width items-baseline">
                      <span class="eyebrow">01</span>
                      <span class="section-title q-ml-md">Statistical signals</span>
                      <q-space />
                      <span class="font-mono section-num"
                            :class="aiClass(detectStore.result.signals.statistical.score)">
                        {{ pct(detectStore.result.signals.statistical.score) }} ai
                      </span>
                    </div>
                  </template>
                  <div class="row q-col-gutter-md signal-body">
                    <div class="col-6 col-md-3 stat-cell">
                      <span class="eyebrow">burstiness sd</span>
                      <span class="font-mono stat-num">{{ num(statContrib?.burstiness?.sd) }}</span>
                    </div>
                    <div class="col-6 col-md-3 stat-cell">
                      <span class="eyebrow">type-token ratio</span>
                      <span class="font-mono stat-num">{{ num(statContrib?.ttr?.ttr, 3) }}</span>
                    </div>
                    <div class="col-6 col-md-3 stat-cell">
                      <span class="eyebrow">sentence cv</span>
                      <span class="font-mono stat-num">{{ num(statContrib?.sentence_cv?.cv, 3) }}</span>
                    </div>
                    <div class="col-6 col-md-3 stat-cell">
                      <span class="eyebrow">format violations</span>
                      <span class="font-mono stat-num">{{ statContrib?.formatting?.violations ?? 0 }}</span>
                    </div>
                  </div>
                </q-expansion-item>

                <!-- patterns -->
                <q-expansion-item
                  v-if="detectStore.result.signals?.patterns"
                  expand-icon="expand_more"
                  class="signal-item"
                  header-class="signal-header"
                >
                  <template #header>
                    <div class="row full-width items-baseline">
                      <span class="eyebrow">02</span>
                      <span class="section-title q-ml-md">Pattern matches</span>
                      <q-space />
                      <span class="font-mono section-num">{{ matches.length }} found</span>
                    </div>
                  </template>
                  <div class="signal-body">
                    <div v-if="matches.length === 0" class="empty-note">
                      No banned phrases or structural anti-patterns detected.
                    </div>
                    <ul v-else class="matches-list">
                      <li v-for="(m, i) in matches" :key="i" class="match-row">
                        <span class="sev-dot" :class="`sev-${m.severity}`"></span>
                        <span class="font-mono match-name">{{ m.name }}</span>
                        <span class="match-cat">{{ m.category.replace('phrase:', '').replace('structure:', '') }}</span>
                        <span v-if="m.suggestion" class="match-fix">→ {{ m.suggestion }}</span>
                      </li>
                    </ul>
                  </div>
                </q-expansion-item>

                <!-- LLM judge -->
                <q-expansion-item
                  v-if="detectStore.result.signals?.llm_judge"
                  expand-icon="expand_more"
                  class="signal-item"
                  header-class="signal-header"
                >
                  <template #header>
                    <div class="row full-width items-baseline">
                      <span class="eyebrow">03</span>
                      <span class="section-title q-ml-md">LLM rubric</span>
                      <q-space />
                      <span v-if="!detectStore.result.signals.llm_judge.error"
                            class="font-mono section-num"
                            :class="aiClass(detectStore.result.signals.llm_judge.score)">
                        {{ pct(detectStore.result.signals.llm_judge.score) }} ai
                      </span>
                    </div>
                  </template>
                  <div class="signal-body">
                    <div v-if="detectStore.result.signals.llm_judge.error" class="empty-note">
                      {{ detectStore.result.signals.llm_judge.error }}
                    </div>
                    <template v-else>
                      <p v-if="detectStore.result.signals.llm_judge.summary"
                         class="judge-summary q-mb-md">
                        {{ detectStore.result.signals.llm_judge.summary }}
                      </p>
                      <div v-if="rubricEntries.length" class="rubric-grid">
                        <div v-for="e in rubricEntries" :key="e.id" class="rubric-row">
                          <div class="rubric-head">
                            <span class="font-mono rubric-id">{{ e.id }}</span>
                            <span class="font-mono rubric-pct">{{ pct(e.score) }} human</span>
                          </div>
                          <div class="rubric-bar">
                            <div class="rubric-bar-fill"
                                 :style="{ width: `${e.score * 100}%`, background: rubricBarColor(e.score) }"></div>
                          </div>
                          <div v-if="e.evidence" class="rubric-ev">{{ e.evidence }}</div>
                        </div>
                      </div>
                    </template>
                  </div>
                </q-expansion-item>

                <!-- sentences (closed by default — usually long) -->
                <q-expansion-item
                  v-if="detectStore.result.signals?.llm_judge?.sentence_scores?.length"
                  expand-icon="expand_more"
                  class="signal-item"
                  header-class="signal-header"
                >
                  <template #header>
                    <div class="row full-width items-baseline">
                      <span class="eyebrow">04</span>
                      <span class="section-title q-ml-md">Sentence level</span>
                      <q-space />
                      <span class="font-mono section-num">
                        {{ detectStore.result.signals.llm_judge.sentence_aggregate?.count ?? 0 }} sentences
                        · mean {{ pct(detectStore.result.signals.llm_judge.sentence_aggregate?.mean) }}
                      </span>
                    </div>
                  </template>
                  <div class="signal-body">
                    <ol class="sentence-list">
                      <li v-for="s in sortedSentences" :key="s.index" class="sentence-row">
                        <span class="font-mono sent-score"
                              :class="aiClass(s.score)">{{ pct(s.score) }}</span>
                        <div class="sent-body">
                          <p class="sent-text">{{ s.text }}</p>
                          <p v-if="s.reason" class="sent-reason">{{ s.reason }}</p>
                        </div>
                      </li>
                    </ol>
                  </div>
                </q-expansion-item>
              </div>

              <div class="editorial-rule q-my-lg"></div>
              <div class="meta-row eyebrow">
                <span>model · {{ detectStore.result.metadata.model_version }}</span>
                <span>rubric · {{ detectStore.result.metadata.rubric_version }}</span>
                <span>mode · {{ detectStore.result.metadata.mode }}</span>
                <span>{{ detectStore.result.metadata.duration_ms }}ms</span>
                <span v-if="detectStore.result.metadata.cached" class="cached">cached</span>
              </div>
            </template>
          </q-tab-panel>

          <!-- ============ REWRITE TAB ============ -->
          <q-tab-panel name="rewrite" class="q-pa-none">
            <div class="rewriter-form q-mb-md">
              <div class="row q-col-gutter-md">
                <div class="col-12 col-md-6">
                  <div class="eyebrow q-mb-xs">target voice</div>
                  <q-select
                    v-model="voice"
                    :options="voiceOptions"
                    emit-value map-options outlined dense
                    color="primary"
                  />
                </div>
                <div class="col-12 col-md-6">
                  <div class="eyebrow q-mb-xs">mode</div>
                  <q-btn-toggle
                    v-model="rewriteMode"
                    :options="modeOptions"
                    color="grey-3"
                    text-color="grey-8"
                    toggle-color="primary"
                    toggle-text-color="white"
                    rounded
                    unelevated
                    no-caps
                    dense
                  />
                </div>
              </div>

              <q-expansion-item
                icon="tune"
                dense
                expand-icon-class="text-grey-7"
                header-class="advanced-header"
                label="Advanced"
                class="q-mt-md"
              >
                <div class="row q-col-gutter-md q-mt-sm">
                  <div class="col-6 col-md-3">
                    <div class="eyebrow q-mb-xs">target AI ≤</div>
                    <q-input v-model.number="targetAi" type="number" step="0.05" min="0.05" max="0.5"
                             outlined dense />
                  </div>
                  <div class="col-6 col-md-3">
                    <div class="eyebrow q-mb-xs">max iterations</div>
                    <q-input v-model.number="maxIterations" type="number" step="1" min="1" max="4"
                             outlined dense />
                  </div>
                  <div class="col-12">
                    <div class="eyebrow q-mb-xs">extra voice instructions</div>
                    <q-input v-model="customVoice" type="textarea" autogrow outlined dense
                             placeholder="e.g. keep one rhetorical question, no emoji" />
                  </div>
                </div>
              </q-expansion-item>

              <div class="row justify-end q-mt-md">
                <q-btn label="Rewrite"
                       unelevated no-caps
                       class="bg-primary text-white"
                       :loading="rewriteStore.loading"
                       :disable="!canRewrite"
                       @click="handleRewrite">
                  <template #loading><q-spinner-dots /></template>
                </q-btn>
              </div>
            </div>

            <q-banner v-if="rewriteStore.error" class="bg-red-1 text-red-10 q-mb-md" rounded dense>
              <template #avatar><q-icon name="error_outline" /></template>
              {{ rewriteStore.error }}
            </q-banner>

            <div v-if="rewriteStore.loading" class="loader">
              <div class="loader-pulse"></div>
              <div class="eyebrow q-mt-md">rewriting</div>
            </div>

            <template v-if="rewriteStore.result">
              <div class="row items-center q-mb-md">
                <span class="eyebrow">result</span>
                <q-space />
                <span class="font-mono"
                      :class="rewriteStore.result.target_reached ? 'sev-bg-low' : 'sev-bg-medium'"
                      style="padding: 4px 8px; border-radius: 2px;">
                  {{ rewriteStore.result.target_reached ? 'target reached' : 'best effort' }}
                </span>
              </div>

              <div class="ba-grid q-mb-md">
                <div class="ba-cell">
                  <span class="eyebrow">before</span>
                  <span class="ba-num font-mono"
                        :class="aiClass(rewriteStore.result.before.ai_probability)">
                    {{ pct(rewriteStore.result.before.ai_probability) }}
                  </span>
                  <span class="ba-verdict">{{ verdictLabel(rewriteStore.result.before.verdict) }}</span>
                </div>
                <div class="ba-arrow font-display">→</div>
                <div class="ba-cell">
                  <span class="eyebrow">after</span>
                  <span class="ba-num font-mono"
                        :class="aiClass(rewriteStore.result.after.ai_probability)">
                    {{ pct(rewriteStore.result.after.ai_probability) }}
                  </span>
                  <span class="ba-verdict">{{ verdictLabel(rewriteStore.result.after.verdict) }}</span>
                </div>
                <div v-if="rewriteDelta > 0.001" class="ba-delta">
                  <span class="eyebrow">delta</span>
                  <span class="font-mono ba-delta-num">−{{ pct(rewriteDelta) }}</span>
                </div>
              </div>

              <div class="rewrite-output">
                <div class="row items-center q-mb-xs">
                  <span class="eyebrow">rewritten</span>
                  <q-space />
                  <q-btn flat dense no-caps icon="content_copy" label="Copy" size="sm"
                         @click="copyRewritten" />
                  <q-btn flat dense no-caps icon="north" label="Use as input" size="sm"
                         color="primary" @click="useRewrittenAsInput" />
                </div>
                <div class="rewrite-body">{{ rewriteStore.result.rewritten_text }}</div>
              </div>

              <section v-if="rewriteStore.result.changes.length" class="q-mt-lg">
                <div class="row items-baseline q-mb-sm">
                  <span class="eyebrow">changes</span>
                  <q-space />
                  <span class="font-mono section-num">{{ rewriteStore.result.changes.length }}</span>
                </div>
                <ul class="changes-list">
                  <li v-for="(c, i) in rewriteStore.result.changes" :key="i">{{ c }}</li>
                </ul>
                <p v-if="rewriteStore.result.preserved_note" class="preserved q-mt-md">
                  <span class="eyebrow">preserved</span>
                  {{ rewriteStore.result.preserved_note }}
                </p>
              </section>

              <section v-if="rewriteStore.result.iterations.length > 1" class="q-mt-lg">
                <div class="row items-baseline q-mb-sm">
                  <span class="eyebrow">iterations</span>
                </div>
                <ol class="iter-list">
                  <li v-for="it in rewriteStore.result.iterations" :key="it.index" class="iter-row">
                    <span class="font-mono iter-idx">#{{ it.index }}</span>
                    <span class="font-mono iter-pct"
                          :class="aiClass(it.ai_probability)">{{ pct(it.ai_probability) }}</span>
                    <span class="iter-verdict">{{ verdictLabel(it.verdict as Verdict) }}</span>
                    <span v-if="it.summary" class="iter-summary">— {{ it.summary }}</span>
                  </li>
                </ol>
              </section>

              <div class="editorial-rule q-my-lg"></div>
              <div class="meta-row eyebrow">
                <span>model · {{ rewriteStore.result.model }}</span>
                <span>voice · {{ rewriteStore.result.voice ?? 'auto' }}</span>
                <span>{{ rewriteStore.result.duration_ms }}ms</span>
                <span>
                  {{ rewriteStore.result.usage.prompt_tokens }} in ·
                  {{ rewriteStore.result.usage.completion_tokens }} out
                </span>
              </div>
            </template>
          </q-tab-panel>

        </q-tab-panels>
      </section>
    </div>
  </q-page>
</template>

<style scoped lang="scss">
.workbench {
  padding: 32px 28px 80px;
  min-height: calc(100vh - 64px);
}

.wb-grid {
  display: grid;
  grid-template-columns: minmax(420px, 620px) minmax(0, 1fr);
  gap: 36px;
  max-width: 1520px;
  margin: 0 auto;
}

// ===== SOURCE (left, sticky) =====
.wb-source {
  position: sticky;
  top: 96px;
  align-self: start;
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-height: calc(100vh - 112px);
  overflow-y: auto;
  padding-right: 6px;

  // Subtle scrollbar matching the editor / preview cards.
  &::-webkit-scrollbar { width: 8px; }
  &::-webkit-scrollbar-thumb { background: var(--rule-strong); border-radius: 4px; }
  &::-webkit-scrollbar-track { background: transparent; }
}

// --- Shared height for both view modes (preview & edit) so the panel
// --- doesn't jump on mode swap. Tweak --source-height in one place.
:root, .wb-source {
  --source-height: clamp(360px, calc(100vh - 260px), 760px);
}

.source-input :deep(.q-field__control) {
  height: var(--source-height);
  min-height: var(--source-height);
  max-height: var(--source-height);
  padding: 0;
}
.source-input :deep(.q-field__native),
.source-input :deep(.q-field__inner) {
  height: 100%;
}
.source-input :deep(textarea) {
  font-family: var(--font-mono);
  font-size: 13px;
  line-height: 1.6;
  color: var(--ink);
  height: 100% !important;
  max-height: 100% !important;
  resize: none;
  overflow-y: auto;
  padding: 16px 18px;

  &::-webkit-scrollbar { width: 8px; }
  &::-webkit-scrollbar-thumb { background: var(--rule-strong); border-radius: 4px; }
  &::-webkit-scrollbar-track { background: transparent; }
}

.source-annotated {
  background: #FFFFFF;
  border: 1px solid var(--field-border);
  border-radius: 6px;
  padding: 16px 18px;
  height: var(--source-height);
  min-height: var(--source-height);
  max-height: var(--source-height);
  overflow-y: auto;
  cursor: text;
  transition: border-color 120ms ease, box-shadow 120ms ease;

  // Subtle scrollbar so long source texts stay readable.
  &::-webkit-scrollbar { width: 8px; }
  &::-webkit-scrollbar-thumb { background: var(--rule-strong); border-radius: 4px; }
  &::-webkit-scrollbar-track { background: transparent; }
}
.source-annotated:hover,
.source-annotated:focus-visible {
  border-color: var(--accent);
  outline: none;
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
.source-hint { color: var(--ink-mute); margin-left: 8px; }
.clear-btn { color: var(--ink-mute); font-size: 12px; letter-spacing: 0.04em; }
.clear-btn:hover { color: var(--accent); }
.mono-count {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-mute);
  letter-spacing: 0.04em;
}

// ===== PANEL (right) =====
.wb-panel { min-width: 0; }
.wb-titlebar { margin-bottom: 32px; }
.wb-title {
  font-size: clamp(36px, 5vw, 56px);
  line-height: 1.02;
  color: var(--ink);
  letter-spacing: -0.04em;
  max-width: 720px;
}
.accent { color: var(--accent); }

.wb-tabs { margin-bottom: 4px; }
.wb-tabs :deep(.q-tabs__content) { gap: 4px; }
.wb-tabs :deep(.q-tab) {
  padding: 0 28px;
  min-height: 44px;
}
.wb-tabs :deep(.q-tab__content) { padding: 0; }
.wb-tabs :deep(.q-tab__label) {
  font-family: var(--font-mono);
  letter-spacing: 0.04em;
}

// ===== HERO (gauge + summary) =====
.result-hero {
  display: grid;
  grid-template-columns: minmax(0, 280px) minmax(0, 1fr);
  gap: 36px;
  align-items: center;
}
.gauge-wrap {
  position: relative;
  width: 100%;
  max-width: 280px;
  aspect-ratio: 360 / 200;
}
.gauge-svg { width: 100%; height: 100%; display: block; }
.gauge-readout {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  padding-bottom: 4px;
}
.gauge-num {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: clamp(44px, 6vw, 64px);
  font-weight: 500;
  letter-spacing: -0.04em;
  line-height: 1;
  color: var(--ink);
}
.gauge-pct { font-size: 0.45em; color: var(--ink-mute); margin-left: 4px; }

.verdict-line { margin: 4px 0 14px; }
.verdict-word {
  font-size: clamp(32px, 4.4vw, 48px);
  letter-spacing: -0.03em;
  color: var(--ink);
  line-height: 1;
}
.kv-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 28px;
  max-width: 420px;
}
.kv {
  display: flex;
  flex-direction: column;
  gap: 2px;
  border-top: 1px solid var(--rule);
  padding-top: 6px;
}
.kv-num {
  font-size: 17px;
  font-variant-numeric: tabular-nums;
  color: var(--ink);
}

.rewrite-cta {
  padding: 8px 18px;
  font-weight: 500;
  letter-spacing: -0.01em;
}
.rewrite-cta :deep(.q-btn__content) {
  gap: 10px;
}

// ===== SECTIONS (collapsible) =====
.signal-sections {
  display: flex;
  flex-direction: column;
  border-top: 1px solid var(--rule);
}
.signal-item {
  border-bottom: 1px solid var(--rule);
}
.signal-item :deep(.q-expansion-item__container > .q-item) {
  background: transparent !important;
  min-height: 56px;
  padding: 8px 0;
}
.signal-item :deep(.q-item__section--main) { padding-right: 12px; }
.signal-item :deep(.q-focus-helper) { display: none; }
.signal-item :deep(.q-expansion-item__content) {
  padding: 4px 0 20px 0;
}
.signal-item :deep(.q-icon) { color: var(--ink-mute); }
.signal-body { padding: 6px 0 4px; }

.section-title {
  font-family: var(--font-ui);
  font-size: 16px;
  font-weight: 500;
  letter-spacing: -0.01em;
  color: var(--ink);
}
.section-num {
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  padding: 3px 7px;
  border-radius: 2px;
  letter-spacing: 0.04em;
  text-transform: lowercase;
}

.stat-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
  border-top: 1px solid var(--rule);
  padding-top: 8px;
}
.stat-num {
  font-size: 20px;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
  color: var(--ink);
}

.empty-note {
  font-size: 14px;
  color: var(--ink-mute);
  font-style: italic;
}

// ===== MATCHES LIST =====
.matches-list {
  list-style: none;
  margin: 0;
  padding: 0;
  border-top: 1px solid var(--rule);
}
.match-row {
  display: grid;
  grid-template-columns: 16px minmax(120px, 220px) 100px minmax(0, 1fr);
  gap: 12px;
  align-items: center;
  padding: 10px 0;
  border-bottom: 1px solid var(--rule);
  font-size: 14px;
}
.sev-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
}
.match-name { color: var(--ink); }
.match-cat { font-size: 12px; color: var(--ink-mute); letter-spacing: 0.04em; }
.match-fix { color: var(--ink-soft); font-size: 13px; }

// ===== RUBRIC =====
.judge-summary {
  font-family: var(--font-ui);
  font-size: 15px;
  line-height: 1.55;
  color: var(--ink-soft);
  max-width: 700px;
}
.rubric-grid {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.rubric-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.rubric-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  font-size: 13px;
}
.rubric-id { color: var(--ink); letter-spacing: 0.04em; text-transform: lowercase; }
.rubric-pct { color: var(--ink-mute); font-variant-numeric: tabular-nums; }
.rubric-bar {
  height: 3px;
  background: var(--rule);
  overflow: hidden;
}
.rubric-bar-fill { height: 100%; }
.rubric-ev {
  font-size: 12px;
  color: var(--ink-mute);
  line-height: 1.5;
  margin-top: 2px;
}

// ===== SENTENCES =====
.sentence-list { list-style: none; margin: 0; padding: 0; border-top: 1px solid var(--rule); }
.sentence-row {
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr);
  gap: 16px;
  padding: 14px 0;
  border-bottom: 1px solid var(--rule);
}
.sent-score {
  font-size: 13px;
  padding: 4px 6px;
  border-radius: 2px;
  height: fit-content;
  font-variant-numeric: tabular-nums;
}
.sent-text {
  font-family: var(--font-mono);
  font-size: 13px;
  line-height: 1.6;
  color: var(--ink);
  margin: 0 0 4px;
}
.sent-reason {
  font-size: 12px;
  color: var(--ink-mute);
  margin: 0;
  line-height: 1.5;
}

// ===== META FOOTER =====
.meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 24px;
  color: var(--ink-mute);
}
.cached { color: var(--accent-3); }

// ===== LOADER =====
.loader {
  padding: 48px 0;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.loader-pulse {
  width: 60px;
  height: 60px;
  border: 1px solid var(--rule);
  border-top: 2px solid var(--accent);
  border-radius: 50%;
  animation: spin 1.1s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

// ===== REWRITER =====
.advanced-header :deep(.q-item__label) {
  font-family: var(--font-mono);
  font-size: 12px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--ink-mute);
}

.ba-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 24px;
  padding: 20px 24px;
  border: 1px solid var(--rule);
  border-radius: 6px;
  background: var(--paper-2);
}
.ba-cell { display: flex; flex-direction: column; gap: 4px; }
.ba-num {
  font-size: 40px;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
  padding: 0 6px;
  border-radius: 2px;
  width: fit-content;
}
.ba-verdict { font-size: 13px; color: var(--ink-soft); }
.ba-arrow { font-size: 44px; color: var(--ink-mute); }
.ba-delta { display: flex; flex-direction: column; align-items: flex-end; gap: 2px; }
.ba-delta-num { font-size: 24px; color: var(--accent-3); }

.rewrite-output {
  border: 1px solid var(--rule);
  border-radius: 6px;
  padding: 16px 20px;
  background: #FFFFFF;
}
.rewrite-body {
  font-family: var(--font-mono);
  font-size: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
  color: var(--ink);
}

.changes-list, .iter-list {
  margin: 0;
  padding: 0 0 0 20px;
  font-size: 14px;
  color: var(--ink-soft);
  line-height: 1.55;
}
.changes-list li, .iter-list li { margin-bottom: 6px; }
.preserved { font-size: 13px; color: var(--ink-mute); }

.iter-row {
  list-style: none;
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: baseline;
  padding: 8px 0;
  border-bottom: 1px solid var(--rule);
}
.iter-idx { color: var(--ink-mute); }
.iter-pct { font-size: 15px; padding: 2px 6px; border-radius: 2px; }
.iter-verdict { color: var(--ink); }
.iter-summary { color: var(--ink-mute); font-size: 13px; }

// ===== RESPONSIVE =====
@media (max-width: 1199px) {
  .wb-grid { grid-template-columns: 1fr; gap: 24px; }
  .wb-source { position: relative; top: 0; max-height: none; }
  .result-hero { grid-template-columns: 1fr; gap: 24px; }
  .gauge-wrap { max-width: 320px; margin: 0 auto; }
  .ba-grid { grid-template-columns: 1fr; }
  .ba-arrow { display: none; }
}
</style>
