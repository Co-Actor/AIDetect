<script setup lang="ts">
import { ref, computed } from 'vue';
import { useRewriteStore } from 'src/stores/rewrite';
import type { Mode } from 'src/types/detection';
import type { VoicePreset } from 'src/types/rewrite';

const store = useRewriteStore();

const text = ref('');
const mode = ref<Mode>('balanced');
const voice = ref<VoicePreset | null>(null);
const customVoice = ref('');
const targetAi = ref(0.3);
const maxIterations = ref(2);

const modeOptions = [
  { label: 'Fast', value: 'fast' },
  { label: 'Balanced', value: 'balanced' },
  { label: 'Thorough', value: 'thorough' },
];

const voiceOptions = [
  { label: 'Auto (general human)', value: null },
  { label: 'Casual tech blog', value: 'casual_tech_blog' },
  { label: 'Personal essay', value: 'personal_essay' },
  { label: 'Business — no buzzwords', value: 'business_minus_buzzwords' },
  { label: 'LinkedIn human', value: 'linkedin_human' },
];

const MAX_CHARS = 50_000;
const canRewrite = computed(() => text.value.trim().length > 0 && !store.loading);

async function handleRewrite() {
  if (!canRewrite.value) return;
  await store.rewrite(
    text.value,
    mode.value,
    voice.value,
    customVoice.value.trim() || null,
    targetAi.value,
    maxIterations.value,
  );
}

function aiBarColor(p: number): string {
  if (p < 0.3) return 'positive';
  if (p < 0.6) return 'warning';
  return 'negative';
}

function pct(p: number): string {
  return `${Math.round(p * 100)}%`;
}

const delta = computed(() => {
  if (!store.result) return 0;
  return store.result.before.ai_probability - store.result.after.ai_probability;
});
</script>

<template>
  <q-page class="q-pa-md">
    <div class="row justify-center">
      <div class="col-12 col-md-10 col-lg-9">

        <q-card flat bordered class="q-mb-md">
          <q-card-section>
            <div class="text-h6 q-mb-sm">Rewrite text to read more human</div>
            <q-input
              v-model="text"
              type="textarea"
              autogrow
              outlined
              :maxlength="MAX_CHARS"
              :counter="true"
              placeholder="Paste the AI-detected text. The rewriter will replace banned phrases, break parallel structures and re-cast AI-like sentences, while preserving facts, numbers, code and URLs."
              class="q-mb-md"
            />

            <div class="row q-gutter-md q-mb-md">
              <div class="col-auto">
                <div class="text-caption text-grey-7 q-mb-xs">Mode</div>
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
              <div class="col-12 col-sm">
                <q-select
                  v-model="voice"
                  :options="voiceOptions"
                  label="Target voice"
                  emit-value
                  map-options
                  outlined
                  dense
                />
              </div>
            </div>

            <q-expansion-item icon="tune" label="Advanced">
              <q-card-section class="row q-gutter-md">
                <q-input
                  v-model.number="targetAi"
                  type="number"
                  label="Target AI probability"
                  hint="Stop when ai_p drops below this"
                  step="0.05"
                  min="0.05"
                  max="0.5"
                  outlined
                  dense
                  class="col-auto"
                  style="width: 180px"
                />
                <q-input
                  v-model.number="maxIterations"
                  type="number"
                  label="Max iterations"
                  step="1"
                  min="1"
                  max="4"
                  outlined
                  dense
                  class="col-auto"
                  style="width: 140px"
                />
                <q-input
                  v-model="customVoice"
                  type="textarea"
                  label="Extra voice instructions (optional)"
                  hint="E.g. 'keep one rhetorical question in the middle, no emoji'"
                  outlined
                  dense
                  autogrow
                  class="col-12"
                />
              </q-card-section>
            </q-expansion-item>

            <div class="row justify-end q-mt-md">
              <q-btn
                label="Rewrite"
                color="primary"
                icon="auto_fix_high"
                :loading="store.loading"
                :disable="!canRewrite"
                unelevated
                no-caps
                @click="handleRewrite"
              >
                <template #loading>
                  <q-spinner-dots />
                </template>
              </q-btn>
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
          <q-card-section>
            <div class="row items-center q-gutter-md">
              <div class="col-auto">
                <div class="text-h6">Result</div>
              </div>
              <q-space />
              <q-chip
                :color="store.result.target_reached ? 'positive' : 'warning'"
                text-color="white"
                :icon="store.result.target_reached ? 'check_circle' : 'info'"
                :label="store.result.target_reached ? 'Target reached' : 'Best effort'"
              />
            </div>
          </q-card-section>

          <q-card-section>
            <div class="row q-col-gutter-md">
              <div class="col-12 col-sm-6">
                <div class="text-overline text-grey-7">Before</div>
                <div class="row items-center q-gutter-sm q-mb-sm">
                  <q-circular-progress
                    :value="Math.round(store.result.before.ai_probability * 100)"
                    size="56px"
                    :thickness="0.18"
                    :color="aiBarColor(store.result.before.ai_probability)"
                    track-color="grey-3"
                    show-value
                  >
                    <span class="text-caption text-weight-bold">
                      {{ pct(store.result.before.ai_probability) }}
                    </span>
                  </q-circular-progress>
                  <q-badge :color="aiBarColor(store.result.before.ai_probability)">
                    {{ store.result.before.verdict }}
                  </q-badge>
                </div>
              </div>
              <div class="col-12 col-sm-6">
                <div class="text-overline text-grey-7">After</div>
                <div class="row items-center q-gutter-sm q-mb-sm">
                  <q-circular-progress
                    :value="Math.round(store.result.after.ai_probability * 100)"
                    size="56px"
                    :thickness="0.18"
                    :color="aiBarColor(store.result.after.ai_probability)"
                    track-color="grey-3"
                    show-value
                  >
                    <span class="text-caption text-weight-bold">
                      {{ pct(store.result.after.ai_probability) }}
                    </span>
                  </q-circular-progress>
                  <q-badge :color="aiBarColor(store.result.after.ai_probability)">
                    {{ store.result.after.verdict }}
                  </q-badge>
                  <span v-if="delta > 0.001" class="text-positive text-weight-medium">
                    −{{ pct(delta) }}
                  </span>
                </div>
              </div>
            </div>
          </q-card-section>

          <q-separator />

          <q-card-section>
            <div class="row q-col-gutter-md">
              <div class="col-12 col-md-6">
                <div class="text-overline text-grey-7 q-mb-xs">Original</div>
                <div class="diff-pane diff-before">{{ text }}</div>
              </div>
              <div class="col-12 col-md-6">
                <div class="text-overline text-grey-7 q-mb-xs">Rewritten</div>
                <div class="diff-pane diff-after">{{ store.result.rewritten_text }}</div>
                <q-btn
                  icon="content_copy"
                  label="Copy"
                  flat
                  no-caps
                  size="sm"
                  class="q-mt-sm"
                  @click="() => store.result && navigator.clipboard.writeText(store.result.rewritten_text)"
                />
              </div>
            </div>
          </q-card-section>

          <q-expansion-item
            v-if="store.result.changes.length"
            icon="edit_note"
            :label="`Changes (${store.result.changes.length})`"
            header-class="text-weight-medium"
          >
            <q-card-section>
              <q-list dense>
                <q-item v-for="(c, i) in store.result.changes" :key="i" class="q-px-none">
                  <q-item-section avatar>
                    <q-icon name="check" color="positive" />
                  </q-item-section>
                  <q-item-section>{{ c }}</q-item-section>
                </q-item>
              </q-list>
              <div v-if="store.result.preserved_note" class="text-caption text-grey-7 q-mt-md">
                <q-icon name="lock" class="q-mr-xs" />
                Preserved: {{ store.result.preserved_note }}
              </div>
            </q-card-section>
          </q-expansion-item>

          <q-expansion-item
            v-if="store.result.iterations.length > 1"
            icon="timeline"
            :label="`Iterations (${store.result.iterations.length})`"
            header-class="text-weight-medium"
          >
            <q-card-section>
              <q-list separator dense>
                <q-item v-for="it in store.result.iterations" :key="it.index" class="q-px-none">
                  <q-item-section avatar>
                    <q-badge :color="aiBarColor(it.ai_probability)" :label="`#${it.index}`" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>
                      AI {{ pct(it.ai_probability) }} — {{ it.verdict }}
                    </q-item-label>
                    <q-item-label v-if="it.summary" caption>{{ it.summary }}</q-item-label>
                  </q-item-section>
                </q-item>
              </q-list>
            </q-card-section>
          </q-expansion-item>

          <q-separator />

          <q-card-section class="text-caption text-grey-6 row q-gutter-md">
            <span>Model: {{ store.result.model }}</span>
            <span>Voice: {{ store.result.voice ?? 'auto' }}</span>
            <span>Duration: {{ store.result.duration_ms }}ms</span>
            <span>
              Tokens: {{ store.result.usage.prompt_tokens }} in / {{ store.result.usage.completion_tokens }} out
            </span>
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
.diff-pane {
  white-space: pre-wrap;
  font-family: ui-monospace, SFMono-Regular, monospace;
  font-size: 13px;
  line-height: 1.55;
  border-radius: 4px;
  padding: 12px;
  max-height: 480px;
  overflow-y: auto;
  border: 1px solid #e0e0e0;
}
.diff-before {
  background: #fff8e1;
}
.diff-after {
  background: #e8f5e9;
}
</style>
