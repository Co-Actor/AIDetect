<script setup lang="ts">
import { ref, computed } from 'vue';
import { useDetectionStore } from 'src/stores/detection';
import type { Mode, Severity, Verdict } from 'src/types/detection';

const store = useDetectionStore();

const text = ref('');
const mode = ref<Mode>('balanced');

const modeOptions = [
  { label: 'Fast', value: 'fast' },
  { label: 'Balanced', value: 'balanced' },
  { label: 'Thorough', value: 'thorough' },
];

const MAX_CHARS = 50_000;

const canAnalyze = computed(() => text.value.trim().length > 0 && !store.loading);

async function handleAnalyze() {
  if (!canAnalyze.value) return;
  await store.detect(text.value, mode.value);
}

function verdictLabel(verdict: Verdict): string {
  return {
    human: 'Human',
    likely_human: 'Likely Human',
    uncertain: 'Uncertain',
    likely_ai: 'Likely AI',
    ai: 'AI Generated',
  }[verdict];
}

function verdictColor(verdict: Verdict): string {
  return {
    human: 'positive',
    likely_human: 'green-6',
    uncertain: 'warning',
    likely_ai: 'orange-8',
    ai: 'negative',
  }[verdict];
}

function severityColor(severity: Severity): string {
  return { low: 'positive', medium: 'warning', high: 'negative' }[severity];
}

function gaugeColor(p: number): string {
  if (p < 0.3) return 'positive';
  if (p < 0.6) return 'warning';
  return 'negative';
}

const gaugeValue = computed(() =>
  store.result ? Math.round(store.result.result.ai_probability * 100) : 0,
);

const statContrib = computed(() => store.result?.signals?.statistical?.contributors);

const matches = computed(() => store.result?.signals?.patterns?.matches ?? []);

const rubricEntries = computed(() => {
  const rs = store.result?.rubric_scores;
  if (!rs) return [];
  return Object.entries(rs).map(([id, value]) => ({
    id,
    score: value.score,
    evidence: value.evidence,
  }));
});

function rubricColor(score: number): string {
  if (score >= 0.7) return 'positive';
  if (score >= 0.4) return 'warning';
  return 'negative';
}

function aiColor(score: number): string {
  if (score >= 0.7) return 'negative';
  if (score >= 0.4) return 'warning';
  return 'positive';
}

const sortedSentenceScores = computed(() => {
  const ss = store.result?.signals?.llm_judge?.sentence_scores ?? [];
  return [...ss].sort((a, b) => b.score - a.score);
});

function formatNum(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return n.toFixed(digits);
}

function pctScore(s: number | undefined): string {
  if (s === undefined) return '—';
  return `${Math.round(s * 100)}%`;
}

const annotatedHtml = computed(() => {
  const result = store.result;
  if (!result) return '';
  const spans = result.evidence?.spans ?? [];
  const source = text.value;
  if (!source || spans.length === 0) return '';

  const sorted = [...spans].sort((a, b) => a.start - b.start);
  let cursor = 0;
  let out = '';
  for (const span of sorted) {
    const start = Math.max(span.start, cursor);
    const end = Math.min(span.end, source.length);
    if (start > cursor) {
      out += escapeHtml(source.slice(cursor, start));
    }
    if (end > start) {
      const inner = escapeHtml(source.slice(start, end));
      out += `<mark class="span span-${span.severity}" title="${escapeHtml(span.reason)}">${inner}</mark>`;
      cursor = end;
    }
  }
  if (cursor < source.length) out += escapeHtml(source.slice(cursor));
  return out;
});

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/\n/g, '<br>');
}
</script>

<template>
  <q-page class="q-pa-md">
    <div class="row justify-center">
      <div class="col-12 col-md-9 col-lg-7">

        <q-card flat bordered class="q-mb-md">
          <q-card-section>
            <div class="text-h6 q-mb-sm">Paste text to analyze</div>
            <q-input
              v-model="text"
              type="textarea"
              autogrow
              outlined
              :maxlength="MAX_CHARS"
              :counter="true"
              placeholder="Paste the text you want to check here..."
              class="q-mb-md"
            />

            <div class="row items-center q-gutter-md">
              <div class="col-auto">
                <div class="text-caption text-grey-7 q-mb-xs">Analysis mode</div>
                <q-btn-toggle
                  v-model="mode"
                  :options="modeOptions"
                  color="grey-3"
                  text-color="grey-8"
                  toggle-color="primary"
                  toggle-text-color="white"
                  rounded
                  unelevated
                  no-caps
                />
              </div>

              <div class="col-auto q-ml-auto">
                <q-btn
                  label="Analyze"
                  color="primary"
                  icon="search"
                  :loading="store.loading"
                  :disable="!canAnalyze"
                  size="md"
                  unelevated
                  no-caps
                  @click="handleAnalyze"
                >
                  <template #loading>
                    <q-spinner-dots />
                  </template>
                </q-btn>
              </div>
            </div>
          </q-card-section>
        </q-card>

        <q-banner v-if="store.error" class="bg-negative text-white q-mb-md" rounded>
          <template #avatar>
            <q-icon name="error" />
          </template>
          {{ store.error }}
        </q-banner>

        <q-card v-if="store.result" flat bordered class="result-card">
          <q-card-section class="row items-center q-pb-none">
            <div class="text-h6">Detection Result</div>
            <q-space />
            <q-chip
              :color="verdictColor(store.result.result.verdict)"
              text-color="white"
              :label="verdictLabel(store.result.result.verdict)"
              size="md"
            />
          </q-card-section>

          <q-card-section>
            <div class="row items-center justify-around q-py-md">
              <div class="column items-center">
                <q-circular-progress
                  :value="gaugeValue"
                  size="120px"
                  :thickness="0.18"
                  :color="gaugeColor(store.result.result.ai_probability)"
                  track-color="grey-3"
                  show-value
                  class="q-ma-sm"
                >
                  <div class="column items-center">
                    <span class="text-h5 text-weight-bold">{{ gaugeValue }}%</span>
                    <span class="text-caption text-grey-6">AI Score</span>
                  </div>
                </q-circular-progress>
              </div>

              <div class="column q-gutter-sm">
                <div class="row items-center q-gutter-sm">
                  <q-icon name="smart_toy" color="negative" />
                  <span class="text-body2">
                    AI probability:
                    <strong>{{ Math.round(store.result.result.ai_probability * 100) }}%</strong>
                  </span>
                </div>
                <div class="row items-center q-gutter-sm">
                  <q-icon name="person" color="positive" />
                  <span class="text-body2">
                    Human probability:
                    <strong>{{ Math.round(store.result.result.human_probability * 100) }}%</strong>
                  </span>
                </div>
                <div class="row items-center q-gutter-sm">
                  <q-icon name="verified" color="grey-6" />
                  <span class="text-body2">
                    Confidence:
                    <strong>{{ Math.round(store.result.result.confidence * 100) }}%</strong>
                  </span>
                </div>
                <div class="row items-center q-gutter-sm">
                  <q-icon name="flag" :color="severityColor(store.result.result.severity)" />
                  <span class="text-body2">
                    Severity:
                    <q-badge
                      :color="severityColor(store.result.result.severity)"
                      :label="store.result.result.severity.toUpperCase()"
                    />
                  </span>
                </div>
                <div class="row items-center q-gutter-sm">
                  <q-icon name="translate" color="grey-6" />
                  <span class="text-body2">
                    Language:
                    <strong>{{ store.result.request.language_detected ?? 'unknown' }}</strong>
                  </span>
                </div>
              </div>
            </div>
          </q-card-section>

          <q-separator />

          <q-expansion-item
            v-if="store.result.signals?.statistical"
            icon="bar_chart"
            :label="`Statistical signals — ${pctScore(store.result.signals.statistical.score)} AI markers`"
            :caption="`${pctScore(1 - store.result.signals.statistical.score)} match human-typical ranges`"
            group="signals"
            header-class="text-weight-medium"
            default-opened
          >
            <q-card-section>
              <div v-if="statContrib?.flag === 'empty_text'" class="text-grey-7 text-body2">
                Empty text.
              </div>
              <div v-else class="row q-col-gutter-md">
                <q-chip outline color="primary">
                  burstiness SD: {{ formatNum(statContrib?.burstiness?.sd) }}
                  <span v-if="statContrib?.burstiness?.flag" class="q-ml-xs text-grey-6">
                    ({{ statContrib.burstiness.flag }})
                  </span>
                </q-chip>
                <q-chip outline color="primary">
                  TTR: {{ formatNum(statContrib?.ttr?.ttr, 3) }}
                  <q-icon
                    v-if="statContrib?.ttr?.in_range"
                    name="check"
                    color="positive"
                    size="xs"
                    class="q-ml-xs"
                  />
                </q-chip>
                <q-chip outline color="primary">
                  sentence CV: {{ formatNum(statContrib?.sentence_cv?.cv, 3) }}
                </q-chip>
                <q-chip outline color="primary">
                  formatting violations: {{ statContrib?.formatting?.violations ?? 0 }}
                </q-chip>
                <q-chip
                  v-for="flag in statContrib?.formatting?.flags ?? []"
                  :key="flag"
                  outline
                  color="warning"
                  size="sm"
                >
                  {{ flag }}
                </q-chip>
              </div>
            </q-card-section>
          </q-expansion-item>

          <q-expansion-item
            v-if="store.result.signals?.patterns"
            icon="pattern"
            :label="`Pattern matches — ${matches.length} found`"
            :caption="matches.length === 0
              ? 'No banned phrases or structural anti-patterns detected'
              : `${pctScore(store.result.signals.patterns.score)} weighted by severity`"
            group="signals"
            header-class="text-weight-medium"
            default-opened
          >
            <q-card-section>
              <div v-if="matches.length === 0" class="text-grey-7 text-body2">
                No banned phrases or structural anti-patterns matched.
              </div>
              <q-list v-else separator dense>
                <q-item v-for="(m, i) in matches" :key="i" class="q-px-none">
                  <q-item-section avatar>
                    <q-badge
                      :color="severityColor(m.severity)"
                      :label="m.severity.toUpperCase()"
                    />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>
                      <strong>{{ m.name }}</strong>
                      <span class="text-caption text-grey-6 q-ml-sm">{{ m.category }}</span>
                    </q-item-label>
                    <q-item-label v-if="m.suggestion" caption>
                      {{ m.suggestion }}
                    </q-item-label>
                  </q-item-section>
                  <q-item-section side class="text-caption text-grey-6">
                    {{ m.span[0] }}–{{ m.span[1] }}
                  </q-item-section>
                </q-item>
              </q-list>
            </q-card-section>
          </q-expansion-item>

          <q-expansion-item
            v-if="store.result.signals?.llm_judge"
            icon="psychology"
            :label="store.result.signals.llm_judge.error
              ? `LLM judge — ${store.result.signals.llm_judge.model}`
              : `LLM judge — ${pctScore(store.result.signals.llm_judge.score)} AI markers`"
            :caption="store.result.signals.llm_judge.error
              ? undefined
              : store.result.signals.llm_judge.model"
            group="signals"
            header-class="text-weight-medium"
            :default-opened="!store.result.signals.llm_judge.error"
          >
            <q-card-section>
              <q-banner
                v-if="store.result.signals.llm_judge.error"
                class="bg-grey-2 text-grey-8 q-mb-md"
                rounded
                dense
              >
                <template #avatar>
                  <q-icon name="info" color="grey-7" />
                </template>
                {{ store.result.signals.llm_judge.error }}
              </q-banner>
              <div v-else>
                <div class="q-mb-sm row q-gutter-md">
                  <span class="text-body2 text-grey-7">
                    AI markers:
                    <strong>{{ pctScore(store.result.signals.llm_judge.score) }}</strong>
                  </span>
                  <span class="text-body2 text-grey-7">
                    Human markers:
                    <strong>{{ pctScore(1 - store.result.signals.llm_judge.score) }}</strong>
                  </span>
                </div>
                <div
                  v-if="store.result.signals.llm_judge.summary"
                  class="text-body2 text-grey-8 q-mb-md"
                >
                  {{ store.result.signals.llm_judge.summary }}
                </div>
                <div v-if="rubricEntries.length" class="rubric-grid">
                  <div
                    v-for="entry in rubricEntries"
                    :key="entry.id"
                    class="rubric-row"
                  >
                    <div class="row items-center q-gutter-sm q-mb-xs">
                      <span class="rubric-id text-weight-medium">{{ entry.id }}</span>
                      <q-linear-progress
                        :value="entry.score"
                        :color="rubricColor(entry.score)"
                        size="8px"
                        rounded
                        class="rubric-bar"
                      />
                      <span class="rubric-pct text-caption">
                        {{ Math.round(entry.score * 100) }}% human
                      </span>
                    </div>
                    <div v-if="entry.evidence" class="text-caption text-grey-7 rubric-ev">
                      {{ entry.evidence }}
                    </div>
                  </div>
                </div>
              </div>
            </q-card-section>
          </q-expansion-item>

          <q-expansion-item
            v-if="store.result.signals?.llm_judge?.sentence_scores?.length"
            icon="format_list_numbered"
            :label="`Sentence-level — ${store.result.signals.llm_judge.sentence_aggregate?.count ?? 0} sentences, ${pctScore(store.result.signals.llm_judge.sentence_aggregate?.mean)} avg AI`"
            :caption="`max ${pctScore(store.result.signals.llm_judge.sentence_aggregate?.max)}, ${pctScore(store.result.signals.llm_judge.sentence_aggregate?.fraction_ai_like)} flagged`"
            group="signals"
            header-class="text-weight-medium"
          >
            <q-card-section>
              <q-list separator dense>
                <q-item v-for="s in sortedSentenceScores" :key="s.index" class="q-px-none">
                  <q-item-section avatar>
                    <q-badge :color="aiColor(s.score)" :label="`${Math.round(s.score * 100)}%`" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label class="sentence-text">{{ s.text }}</q-item-label>
                    <q-item-label v-if="s.reason" caption>{{ s.reason }}</q-item-label>
                  </q-item-section>
                </q-item>
              </q-list>
            </q-card-section>
          </q-expansion-item>

          <q-expansion-item
            v-if="annotatedHtml"
            icon="highlight"
            :label="`Highlighted text — ${(store.result.evidence?.spans ?? []).length} span(s)`"
            group="signals"
            header-class="text-weight-medium"
          >
            <q-card-section>
              <div class="annotated" v-html="annotatedHtml"></div>
            </q-card-section>
          </q-expansion-item>

          <q-separator />

          <q-card-section class="text-caption text-grey-6 row q-gutter-md">
            <span>Model: {{ store.result.metadata.model_version }}</span>
            <span>Rubric: {{ store.result.metadata.rubric_version }}</span>
            <span>Mode: {{ store.result.metadata.mode }}</span>
            <span>Duration: {{ store.result.metadata.duration_ms }}ms</span>
            <span v-if="store.result.metadata.cached" class="text-positive">cached</span>
          </q-card-section>
        </q-card>

      </div>
    </div>
  </q-page>
</template>

<style scoped lang="scss">
.result-card {
  transition: all 0.3s ease;
}
.annotated {
  white-space: pre-wrap;
  font-family: ui-monospace, SFMono-Regular, monospace;
  font-size: 13px;
  line-height: 1.55;
  background: #fafafa;
  border-radius: 4px;
  padding: 12px;
}
.annotated :deep(.span) {
  border-radius: 3px;
  padding: 0 2px;
}
.annotated :deep(.span-low)    { background: #fff3c4; }
.annotated :deep(.span-medium) { background: #ffd2a3; }
.annotated :deep(.span-high)   { background: #ffb3b3; }

.rubric-grid {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.rubric-row {
  border-left: 2px solid #e0e0e0;
  padding-left: 10px;
}
.rubric-id {
  display: inline-block;
  width: 100px;
  font-size: 13px;
}
.rubric-bar {
  flex: 1;
  min-width: 120px;
}
.rubric-pct {
  width: 80px;
  text-align: right;
  color: #666;
}
.rubric-ev {
  margin-left: 110px;
  font-size: 12px;
  line-height: 1.4;
}

.sentence-text {
  font-size: 13px;
  line-height: 1.5;
  white-space: normal;
}
</style>
