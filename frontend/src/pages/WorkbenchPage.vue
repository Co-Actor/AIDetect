<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useQuasar } from 'quasar';
import { useDetectionStore } from 'src/stores/detection';
import { useRewriteStore } from 'src/stores/rewrite';
import { shareApi } from 'src/services/api';
import DetectionResultView from 'src/components/DetectionResultView.vue';
import type { Mode, Verdict } from 'src/types/detection';
import type { VoicePreset } from 'src/types/rewrite';
import type { QInput } from 'quasar';

const $q = useQuasar();
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

function pct(p: number | undefined | null): string {
  if (p === null || p === undefined || Number.isNaN(p)) return '—';
  return `${Math.round(p * 100)}%`;
}
function verdictLabel(v: Verdict): string {
  return {
    human: 'Human',
    likely_human: 'Likely human',
    uncertain: 'Uncertain',
    likely_ai: 'Likely AI',
    ai: 'AI',
  }[v];
}
function aiClass(p: number): string {
  if (p < 0.3) return 'sev-bg-low';
  if (p < 0.65) return 'sev-bg-medium';
  return 'sev-bg-high';
}

// ===== share =====
const sharing = ref(false);

async function handleShare() {
  if (!detectStore.result) return;
  sharing.value = true;
  try {
    const res = await shareApi.create({
      input_text: text.value,
      mode: detectStore.result.metadata.mode,
    });

    const shareUrl = res.url;

    $q.dialog({
      title: 'Result shared',
      message: shareUrl,
      ok: { label: 'Copy link', unelevated: true, noCaps: true, color: 'primary' },
      cancel: { label: 'Close', flat: true, noCaps: true },
    }).onOk(() => {
      void navigator.clipboard.writeText(shareUrl).then(() => {
        $q.notify({ message: 'Link copied to clipboard', icon: 'content_copy', color: 'positive' });
      });
    });

    $q.notify({ message: 'Share link created', icon: 'share', color: 'positive' });
  } catch (err) {
    $q.notify({
      message: err instanceof Error ? err.message : 'Failed to create share link',
      icon: 'error_outline',
      color: 'negative',
    });
  } finally {
    sharing.value = false;
  }
}

// ===== rewriter =====
const rewriteMode = ref<Mode>('balanced');
const voice = ref<VoicePreset | null>(null);
const customVoice = ref('');
const targetAi = ref(0.3);
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
    text.value,
    rewriteMode.value,
    voice.value,
    customVoice.value.trim() || null,
    targetAi.value,
    maxIterations.value,
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

// ===== source panel =====
const escapeHtml = (s: string) =>
  s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/\n/g, '<br>');

const sourceHasContent = computed(() => text.value.trim().length > 0);

const showAnnotatedPreview = computed(
  () =>
    sourceHasContent.value &&
    detectStore.result !== null &&
    text.value === detectStore.lastAnalyzedText &&
    !isEditing.value,
);

// For WorkbenchPage the annotated preview is built inline (uses text.value directly)
// We don't re-implement it here — the left panel keeps its own mark-up logic.
// (DetectionResultView is used in the result section, which always has sourceText prop.)
const annotatedHtmlForPanel = computed(() => {
  const r = detectStore.result;
  if (!r) return '';
  const spans = r.evidence?.spans ?? [];
  const src = text.value;
  if (!src || spans.length === 0) return '';

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

const sourcePreview = computed(() => annotatedHtmlForPanel.value || escapeHtml(text.value));

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

watch(text, (next) => {
  if (detectStore.result && next !== detectStore.lastAnalyzedText) {
    detectStore.reset();
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
          <span v-if="showAnnotatedPreview" class="eyebrow source-hint">· click to edit</span>
          <q-space />
          <q-btn
            v-if="sourceHasContent"
            flat
            dense
            no-caps
            size="sm"
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
            {{ text.length }}
            <span class="text-grey-5">/ {{ MAX_CHARS }}</span>
          </span>
        </div>

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
            <span class="font-display accent">machine</span>
            , keep the
            <span class="font-display accent">voice</span>
            .
          </h1>
        </div>

        <q-tabs v-model="activeTab" dense class="wb-tabs" align="left" narrow-indicator no-caps>
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
                data-testid="analyze-btn"
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
              <!-- The full result UI is now in DetectionResultView -->
              <DetectionResultView :result="detectStore.result" />

              <!-- Rewrite CTA (kept here because it needs jumpToRewriter) -->
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

              <!-- Share button -->
              <div class="q-mt-md">
                <q-btn
                  data-testid="share-btn"
                  flat
                  no-caps
                  icon="share"
                  label="Share result"
                  color="primary"
                  :loading="sharing"
                  @click="handleShare"
                />
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
                    emit-value
                    map-options
                    outlined
                    dense
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
                    <q-input
                      v-model.number="targetAi"
                      type="number"
                      step="0.05"
                      min="0.05"
                      max="0.5"
                      outlined
                      dense
                    />
                  </div>
                  <div class="col-6 col-md-3">
                    <div class="eyebrow q-mb-xs">max iterations</div>
                    <q-input
                      v-model.number="maxIterations"
                      type="number"
                      step="1"
                      min="1"
                      max="4"
                      outlined
                      dense
                    />
                  </div>
                  <div class="col-12">
                    <div class="eyebrow q-mb-xs">extra voice instructions</div>
                    <q-input
                      v-model="customVoice"
                      type="textarea"
                      autogrow
                      outlined
                      dense
                      placeholder="e.g. keep one rhetorical question, no emoji"
                    />
                  </div>
                </div>
              </q-expansion-item>

              <div class="row justify-end q-mt-md">
                <q-btn
                  label="Rewrite"
                  unelevated
                  no-caps
                  class="bg-primary text-white"
                  :loading="rewriteStore.loading"
                  :disable="!canRewrite"
                  @click="handleRewrite"
                >
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
                <span
                  class="font-mono"
                  :class="rewriteStore.result.target_reached ? 'sev-bg-low' : 'sev-bg-medium'"
                  style="padding: 4px 8px; border-radius: 2px"
                >
                  {{ rewriteStore.result.target_reached ? 'target reached' : 'best effort' }}
                </span>
              </div>

              <div class="ba-grid q-mb-md">
                <div class="ba-cell">
                  <span class="eyebrow">before</span>
                  <span
                    class="ba-num font-mono"
                    :class="aiClass(rewriteStore.result.before.ai_probability)"
                  >
                    {{ pct(rewriteStore.result.before.ai_probability) }}
                  </span>
                  <span class="ba-verdict">
                    {{ verdictLabel(rewriteStore.result.before.verdict) }}
                  </span>
                </div>
                <div class="ba-arrow font-display">→</div>
                <div class="ba-cell">
                  <span class="eyebrow">after</span>
                  <span
                    class="ba-num font-mono"
                    :class="aiClass(rewriteStore.result.after.ai_probability)"
                  >
                    {{ pct(rewriteStore.result.after.ai_probability) }}
                  </span>
                  <span class="ba-verdict">
                    {{ verdictLabel(rewriteStore.result.after.verdict) }}
                  </span>
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
                  <q-btn
                    flat
                    dense
                    no-caps
                    icon="content_copy"
                    label="Copy"
                    size="sm"
                    @click="copyRewritten"
                  />
                  <q-btn
                    flat
                    dense
                    no-caps
                    icon="north"
                    label="Use as input"
                    size="sm"
                    color="primary"
                    @click="useRewrittenAsInput"
                  />
                </div>
                <div class="rewrite-body">{{ rewriteStore.result.rewritten_text }}</div>
              </div>

              <section v-if="rewriteStore.result.changes.length" class="q-mt-lg">
                <div class="row items-baseline q-mb-sm">
                  <span class="eyebrow">changes</span>
                  <q-space />
                  <span class="font-mono section-num">
                    {{ rewriteStore.result.changes.length }}
                  </span>
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
                    <span class="font-mono iter-pct" :class="aiClass(it.ai_probability)">
                      {{ pct(it.ai_probability) }}
                    </span>
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

:root,
.wb-source {
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

.source-annotated {
  background: #ffffff;
  border: 1px solid var(--field-border);
  border-radius: 6px;
  padding: 16px 18px;
  height: var(--source-height);
  min-height: var(--source-height);
  max-height: var(--source-height);
  overflow-y: auto;
  cursor: text;
  transition:
    border-color 120ms ease,
    box-shadow 120ms ease;

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
.source-hint {
  color: var(--ink-mute);
  margin-left: 8px;
}
.clear-btn {
  color: var(--ink-mute);
  font-size: 12px;
  letter-spacing: 0.04em;
}
.clear-btn:hover {
  color: var(--accent);
}
.mono-count {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-mute);
  letter-spacing: 0.04em;
}

// ===== PANEL (right) =====
.wb-panel {
  min-width: 0;
}
.wb-titlebar {
  margin-bottom: 32px;
}
.wb-title {
  font-size: clamp(36px, 5vw, 56px);
  line-height: 1.02;
  color: var(--ink);
  letter-spacing: -0.04em;
  max-width: 720px;
}
.accent {
  color: var(--accent);
}

.wb-tabs {
  margin-bottom: 4px;
}
.wb-tabs :deep(.q-tabs__content) {
  gap: 4px;
}
.wb-tabs :deep(.q-tab) {
  padding: 0 28px;
  min-height: 44px;
}
.wb-tabs :deep(.q-tab__content) {
  padding: 0;
}
.wb-tabs :deep(.q-tab__label) {
  font-family: var(--font-mono);
  letter-spacing: 0.04em;
}

.rewrite-cta {
  padding: 8px 18px;
  font-weight: 500;
  letter-spacing: -0.01em;
}
.rewrite-cta :deep(.q-btn__content) {
  gap: 10px;
}

.section-num {
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  padding: 3px 7px;
  border-radius: 2px;
  letter-spacing: 0.04em;
  text-transform: lowercase;
}

// ===== META FOOTER =====
.meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 24px;
  color: var(--ink-mute);
}

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
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

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
.ba-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.ba-num {
  font-size: 40px;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
  padding: 0 6px;
  border-radius: 2px;
  width: fit-content;
}
.ba-verdict {
  font-size: 13px;
  color: var(--ink-soft);
}
.ba-arrow {
  font-size: 44px;
  color: var(--ink-mute);
}
.ba-delta {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
}
.ba-delta-num {
  font-size: 24px;
  color: var(--accent-3);
}

.rewrite-output {
  border: 1px solid var(--rule);
  border-radius: 6px;
  padding: 16px 20px;
  background: #ffffff;
}
.rewrite-body {
  font-family: var(--font-mono);
  font-size: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
  color: var(--ink);
}

.changes-list,
.iter-list {
  margin: 0;
  padding: 0 0 0 20px;
  font-size: 14px;
  color: var(--ink-soft);
  line-height: 1.55;
}
.changes-list li,
.iter-list li {
  margin-bottom: 6px;
}
.preserved {
  font-size: 13px;
  color: var(--ink-mute);
}

.iter-row {
  list-style: none;
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: baseline;
  padding: 8px 0;
  border-bottom: 1px solid var(--rule);
}
.iter-idx {
  color: var(--ink-mute);
}
.iter-pct {
  font-size: 15px;
  padding: 2px 6px;
  border-radius: 2px;
}
.iter-verdict {
  color: var(--ink);
}
.iter-summary {
  color: var(--ink-mute);
  font-size: 13px;
}

// ===== RESPONSIVE =====
@media (max-width: 1199px) {
  .wb-grid {
    grid-template-columns: 1fr;
    gap: 24px;
  }
  .wb-source {
    position: relative;
    top: 0;
    max-height: none;
  }
  .ba-grid {
    grid-template-columns: 1fr;
  }
  .ba-arrow {
    display: none;
  }
}
</style>
