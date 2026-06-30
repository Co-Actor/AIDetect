<script setup lang="ts">
import { computed } from 'vue';
import type { DetectionResult, Verdict } from 'src/types/detection';

const props = defineProps<{
  result: DetectionResult;
}>();

// ── helpers ────────────────────────────────────────────────────────────────

function verdictLabel(v: Verdict): string {
  return { human: 'Human', likely_human: 'Likely human', uncertain: 'Uncertain', likely_ai: 'Likely AI', ai: 'AI' }[v];
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

// ── gauge ──────────────────────────────────────────────────────────────────

const gaugePercent = computed(() => Math.round(props.result.result.human_probability * 100));
const gaugeStrokeColor = computed(() => {
  const human = props.result.result.human_probability;
  if (human >= 0.70) return 'var(--accent-3)';
  if (human >= 0.35) return 'var(--accent-2)';
  return 'var(--accent)';
});
const arcDashOffset = computed(() => {
  const total = Math.PI * 160;
  return total - (total * gaugePercent.value) / 100;
});

// ── signal accessors ───────────────────────────────────────────────────────

const statContrib = computed(() => props.result.signals?.statistical?.contributors);
const matches = computed(() => props.result.signals?.patterns?.matches ?? []);
const sortedSentences = computed(() => {
  const ss = props.result.signals?.llm_judge?.sentence_scores ?? [];
  return [...ss].sort((a, b) => b.score - a.score);
});
const rubricEntries = computed(() => {
  const rs = props.result.rubric_scores;
  if (!rs) return [];
  return Object.entries(rs).map(([id, v]) => ({ id, score: v.score, evidence: v.evidence }));
});
function rubricBarColor(score: number): string {
  if (score >= 0.7) return 'var(--accent-3)';
  if (score >= 0.4) return 'var(--accent-2)';
  return 'var(--accent)';
}
</script>

<template>
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
          {{ verdictLabel(result.result.verdict) }}
        </span>
      </div>
      <div class="kv-grid">
        <div class="kv">
          <span class="eyebrow">AI</span>
          <span class="font-mono kv-num">{{ pct(result.result.ai_probability) }}</span>
        </div>
        <div class="kv">
          <span class="eyebrow">Human</span>
          <span class="font-mono kv-num">{{ pct(result.result.human_probability) }}</span>
        </div>
        <div class="kv">
          <span class="eyebrow">Confidence</span>
          <span class="font-mono kv-num">{{ pct(result.result.confidence) }}</span>
        </div>
        <div class="kv">
          <span class="eyebrow">Language</span>
          <span class="font-mono kv-num">{{ result.request.language_detected ?? '—' }}</span>
        </div>
      </div>
    </div>
  </div>

  <div class="editorial-rule q-my-lg"></div>

  <!-- collapsible signal sections -->
  <div class="signal-sections">
    <!-- statistical -->
    <q-expansion-item
      v-if="result.signals?.statistical"
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
                :class="aiClass(result.signals.statistical.score)">
            {{ pct(result.signals.statistical.score) }} ai
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
      v-if="result.signals?.patterns"
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
      v-if="result.signals?.llm_judge"
      expand-icon="expand_more"
      class="signal-item"
      header-class="signal-header"
    >
      <template #header>
        <div class="row full-width items-baseline">
          <span class="eyebrow">03</span>
          <span class="section-title q-ml-md">LLM rubric</span>
          <q-space />
          <span v-if="!result.signals.llm_judge.error"
                class="font-mono section-num"
                :class="aiClass(result.signals.llm_judge.score)">
            {{ pct(result.signals.llm_judge.score) }} ai
          </span>
        </div>
      </template>
      <div class="signal-body">
        <div v-if="result.signals.llm_judge.error" class="empty-note">
          {{ result.signals.llm_judge.error }}
        </div>
        <template v-else>
          <p v-if="result.signals.llm_judge.summary"
             class="judge-summary q-mb-md">
            {{ result.signals.llm_judge.summary }}
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

    <!-- sentences -->
    <q-expansion-item
      v-if="result.signals?.llm_judge?.sentence_scores?.length"
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
            {{ result.signals.llm_judge.sentence_aggregate?.count ?? 0 }} sentences
            · mean {{ pct(result.signals.llm_judge.sentence_aggregate?.mean) }}
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
    <span>model · {{ result.metadata.model_version }}</span>
    <span>rubric · {{ result.metadata.rubric_version }}</span>
    <span>mode · {{ result.metadata.mode }}</span>
    <span>{{ result.metadata.duration_ms }}ms</span>
    <span v-if="result.metadata.cached" class="cached">cached</span>
  </div>
</template>

<style scoped lang="scss">
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

// ===== SECTIONS =====
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

// ===== MATCHES =====
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

// ===== RESPONSIVE =====
@media (max-width: 1199px) {
  .result-hero { grid-template-columns: 1fr; gap: 24px; }
  .gauge-wrap { max-width: 320px; margin: 0 auto; }
}
</style>
