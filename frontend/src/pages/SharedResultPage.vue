<script setup lang="ts">
import { ref, computed, onMounted, watch, nextTick } from 'vue';
import { useRoute } from 'vue-router';
import { useQuasar } from 'quasar';
import { shareApi, accessApi } from 'src/services/api';
import type { ShareGetResponse, ShareTrialResponse } from 'src/services/api';
import type { Mode } from 'src/types/detection';
import type { QInput } from 'quasar';
import DetectionResultView from 'src/components/DetectionResultView.vue';
import AnnotatedSource from 'src/components/AnnotatedSource.vue';

const $q = useQuasar();
const route = useRoute();
const token = route.params.token as string;

// ── shared result state ────────────────────────────────────────────────────
const sharedData = ref<ShareGetResponse | null>(null);
const loadError = ref<string | null>(null);
const loadingShared = ref(true);
const notFound = ref(false);

// ── trial state ────────────────────────────────────────────────────────────
const trialText = ref('');
// Trial checks are fixed to the balanced model — other modes are not offered here.
const trialMode = ref<Mode>('balanced');
const trialResult = ref<ShareTrialResponse | null>(null);
const trialAnalyzedText = ref('');
const trialLoading = ref(false);
const isEditingTrial = ref(false);
const trialInputRef = ref<InstanceType<typeof QInput> | null>(null);
const exhausted = ref(false);

// Remaining checks (derived from latest trial response or initial load).
const remaining = ref(0);
const trialLimit = computed(
  () => trialResult.value?.trial_limit ?? sharedData.value?.trial_limit ?? 3,
);
const exhaustedMessage = computed(
  () => `You've used all ${trialLimit.value} free checks. Sign up to keep using AIDetect.`,
);

// Show the annotated read-only view inside "your text" once a result is in and
// the text still matches what was analyzed — same view/edit switch as the product.
const showTrialAnnotated = computed(
  () =>
    trialText.value.trim().length > 0 &&
    trialResult.value !== null &&
    trialText.value === trialAnalyzedText.value &&
    !isEditingTrial.value,
);

function syncRemaining(used: number, limit: number): void {
  remaining.value = Math.max(0, limit - used);
  if (remaining.value === 0) {
    exhausted.value = true;
  }
}

onMounted(async () => {
  try {
    sharedData.value = await shareApi.get(token);
    syncRemaining(sharedData.value.trial_used, sharedData.value.trial_limit);
    if (!sharedData.value.active) {
      exhausted.value = true;
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Not found';
    if (msg.toLowerCase().includes('not found') || msg.includes('404')) {
      notFound.value = true;
    } else {
      loadError.value = msg;
    }
  } finally {
    loadingShared.value = false;
  }
});

async function handleTrial(): Promise<void> {
  if (!trialText.value.trim() || exhausted.value || trialLoading.value) return;
  trialLoading.value = true;
  const submitted = trialText.value;
  try {
    const res = await shareApi.trial(token, { text: submitted, mode: trialMode.value });
    trialResult.value = res;
    trialAnalyzedText.value = submitted;
    isEditingTrial.value = false; // flip "your text" to the annotated view
    syncRemaining(res.trial_used, res.trial_limit);
    if (!res.active) exhausted.value = true;
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Trial failed';
    // 403 = exhausted; message from backend is user-facing.
    if (msg.includes('free checks') || msg.includes('403')) {
      exhausted.value = true;
    } else {
      $q.notify({ message: msg, icon: 'error_outline', color: 'negative' });
    }
  } finally {
    trialLoading.value = false;
  }
}

async function enterTrialEdit(): Promise<void> {
  isEditingTrial.value = true;
  await nextTick();
  trialInputRef.value?.focus?.();
}
function exitTrialEdit(): void {
  isEditingTrial.value = false;
}
function clearTrial(): void {
  trialText.value = '';
  trialResult.value = null;
  trialAnalyzedText.value = '';
  isEditingTrial.value = false;
}

// ── access-request form state ──────────────────────────────────────────────
const requestEmail = ref('');
const requestLoading = ref(false);
const requestSent = ref(false);
const requestSentEmail = ref('');

async function handleAccessRequest(): Promise<void> {
  if (!requestEmail.value.trim() || requestLoading.value) return;
  requestLoading.value = true;
  try {
    await accessApi.request({ email: requestEmail.value.trim(), share_token: token });
    requestSentEmail.value = requestEmail.value.trim();
    requestSent.value = true;
  } catch (err) {
    $q.notify({
      message: err instanceof Error ? err.message : 'Request failed. Please try again.',
      icon: 'error_outline',
      color: 'negative',
    });
  } finally {
    requestLoading.value = false;
  }
}

// Editing the analyzed text invalidates the result (same as the product).
watch(trialText, (next) => {
  if (trialResult.value && next !== trialAnalyzedText.value) {
    trialResult.value = null;
  }
});
</script>

<template>
  <q-layout view="hHh lpr fFf">
    <q-header :elevated="false" class="atelier-header">
      <q-toolbar class="atelier-toolbar">
        <div class="row items-center q-gutter-md">
          <span class="brand-mark font-display">v</span>
          <div class="column items-start" style="line-height: 1">
            <span class="brand-title">AIDetect</span>
            <span class="eyebrow brand-tag">Veracity workbench</span>
          </div>
        </div>
      </q-toolbar>
      <div class="atelier-header-rule" />
    </q-header>

    <q-page-container>
      <q-page class="shared-page">
        <!-- ── loading ── -->
        <div v-if="loadingShared" class="loader flex flex-center column q-pa-xl">
          <div class="loader-pulse"></div>
          <div class="eyebrow q-mt-md">loading shared result</div>
        </div>

        <!-- ── not found ── -->
        <div v-else-if="notFound" class="not-found flex flex-center column q-pa-xl">
          <q-icon name="link_off" size="56px" color="grey-5" />
          <h2 class="not-found-title">Link not found</h2>
          <p class="eyebrow text-grey-6">This share link may have expired or been removed.</p>
          <q-btn unelevated no-caps label="Go to AIDetect" color="primary" class="q-mt-lg" to="/" />
        </div>

        <!-- ── load error ── -->
        <div v-else-if="loadError" class="q-pa-xl">
          <q-banner class="bg-red-1 text-red-10" rounded dense>
            <template #avatar><q-icon name="error_outline" /></template>
            {{ loadError }}
          </q-banner>
        </div>

        <!-- ── result ── -->
        <template v-else-if="sharedData">
          <div class="shared-wrap">
            <!-- Shared detection result: two-pane, same as the product workbench -->
            <div class="wb-grid">
              <aside class="wb-source">
                <div class="eyebrow q-mb-sm">source text</div>
                <AnnotatedSource :result="sharedData.result" :text="sharedData.input_text" />
              </aside>

              <section class="wb-panel">
                <div class="eyebrow shared-label q-mb-md">Shared detection result</div>
                <DetectionResultView :result="sharedData.result" />
              </section>
            </div>

            <div class="editorial-rule q-my-xl"></div>

            <!-- ── Try it yourself ── -->
            <section class="trial-section">
              <div class="row items-center q-mb-lg">
                <div>
                  <h3 class="trial-heading">Try it yourself</h3>
                  <p class="eyebrow text-grey-6">Analyze your own text — no account needed.</p>
                </div>
                <q-space />
                <div v-if="!exhausted" class="trial-badge eyebrow">
                  Free checks left:
                  <strong data-testid="trial-remaining">{{ remaining }}</strong>
                </div>
              </div>

              <!-- trial workbench: two-pane. The grid is ALWAYS rendered so the
                   last result stays visible; when the quota is spent the input is
                   replaced by the exhausted banner, the result remains on the right. -->
              <div class="wb-grid">
                <aside class="wb-source">
                  <!-- spent: banner takes the input's place -->
                  <div v-if="exhausted" data-testid="exhausted-banner" class="exhausted-banner">
                    <q-icon name="lock_outline" size="24px" class="q-mr-sm" />
                    <span>{{ exhaustedMessage }}</span>

                    <!-- request-sent confirmation -->
                    <div
                      v-if="requestSent"
                      data-testid="request-sent"
                      class="access-request-sent eyebrow"
                    >
                      Thanks — we'll email an invitation to {{ requestSentEmail }}.
                    </div>

                    <!-- request-access form -->
                    <q-form
                      v-else
                      class="access-request-form"
                      @submit.prevent="handleAccessRequest"
                    >
                      <q-input
                        data-testid="request-email"
                        v-model="requestEmail"
                        type="email"
                        outlined
                        dense
                        placeholder="your@email.com"
                        :disable="requestLoading"
                        :rules="[(v: string) => !!v || 'Email is required']"
                        class="access-request-input"
                      />
                      <q-btn
                        data-testid="request-submit"
                        type="submit"
                        label="Request access"
                        unelevated
                        no-caps
                        color="primary"
                        :loading="requestLoading"
                        :disable="!requestEmail.trim() || requestLoading"
                        class="q-mt-sm"
                      >
                        <template #loading><q-spinner-dots /></template>
                      </q-btn>
                    </q-form>
                  </div>

                  <!-- still has checks left: the input -->
                  <template v-else>
                    <div class="row items-center q-mb-sm">
                      <span class="eyebrow">your text</span>
                      <span v-if="showTrialAnnotated" class="eyebrow source-hint">
                        · click to edit
                      </span>
                      <q-space />
                      <q-btn
                        v-if="trialText.trim()"
                        data-testid="trial-clear"
                        flat
                        dense
                        no-caps
                        size="sm"
                        icon="close"
                        label="Clear"
                        class="clear-btn"
                        @click="clearTrial"
                      />
                    </div>

                    <!-- view mode: annotated highlights, click to edit -->
                    <div
                      v-if="showTrialAnnotated && trialResult"
                      class="trial-annotated"
                      role="button"
                      tabindex="0"
                      @click="enterTrialEdit"
                      @keydown.enter.prevent="enterTrialEdit"
                    >
                      <AnnotatedSource :result="trialResult.result" :text="trialAnalyzedText" />
                    </div>
                    <!-- edit mode: textarea -->
                    <q-input
                      v-else
                      ref="trialInputRef"
                      data-testid="trial-textarea"
                      v-model="trialText"
                      type="textarea"
                      outlined
                      dense
                      placeholder="Paste text to analyze..."
                      class="trial-input"
                      :disable="trialLoading"
                      @blur="exitTrialEdit"
                    />

                    <div class="row items-center q-gutter-md q-mt-md">
                      <span class="eyebrow">mode</span>
                      <span class="mode-fixed">balanced</span>
                      <q-space />
                      <q-btn
                        data-testid="trial-analyze-btn"
                        label="Analyze"
                        unelevated
                        no-caps
                        color="primary"
                        :loading="trialLoading"
                        :disable="!trialText.trim() || trialLoading"
                        @click="handleTrial"
                      >
                        <template #loading><q-spinner-dots /></template>
                      </q-btn>
                    </div>
                  </template>
                </aside>

                <section class="wb-panel">
                  <template v-if="trialResult">
                    <div class="eyebrow q-mb-md">your result</div>
                    <DetectionResultView :result="trialResult.result" />
                  </template>
                  <div v-else class="trial-placeholder">
                    <q-icon name="science" size="28px" color="grey-5" />
                    <span class="eyebrow q-mt-sm">Run a check to see the breakdown here.</span>
                  </div>
                </section>
              </div>
            </section>
          </div>
        </template>
      </q-page>
    </q-page-container>
  </q-layout>
</template>

<style scoped lang="scss">
.atelier-header {
  background: var(--paper);
  color: var(--ink);
}
.atelier-toolbar {
  min-height: 64px;
  padding: 0 28px;
}
.brand-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  font-size: 32px;
  line-height: 1;
  color: var(--accent);
}
.brand-title {
  font-family: var(--font-ui);
  font-weight: 600;
  font-size: 18px;
  letter-spacing: -0.01em;
  color: var(--ink);
}
.brand-tag {
  margin-top: 2px;
}
.atelier-header-rule {
  height: 1px;
  background: var(--rule);
}

.shared-page {
  padding: 40px 28px 80px;
}
.shared-wrap {
  --source-height: clamp(340px, calc(100vh - 320px), 680px);
  max-width: 1520px;
  margin: 0 auto;
}
.shared-label {
  color: var(--ink-mute);
}

.not-found {
  min-height: 60vh;
  text-align: center;
}
.not-found-title {
  font-family: var(--font-display);
  font-size: 32px;
  letter-spacing: -0.03em;
  color: var(--ink);
  margin: 16px 0 8px;
}

.loader {
  min-height: 40vh;
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

// ── two-pane grid (mirrors the workbench product layout) ──────────────────
.wb-grid {
  display: grid;
  grid-template-columns: minmax(380px, 560px) minmax(0, 1fr);
  gap: 36px;
}
.wb-source {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.wb-panel {
  min-width: 0;
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

// Tall trial input, matching the source field + the annotated view height so
// switching view/edit modes doesn't shift the layout.
.trial-input :deep(.q-field__control) {
  height: var(--source-height);
  padding: 0;
}
.trial-input :deep(.q-field__native),
.trial-input :deep(.q-field__inner) {
  height: 100%;
}
.trial-input :deep(textarea) {
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

.trial-annotated {
  cursor: text;
}
.trial-annotated:hover :deep(.source-annotated),
.trial-annotated:focus-visible :deep(.source-annotated) {
  border-color: var(--accent);
  outline: none;
}

.trial-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  min-height: var(--source-height);
  border: 1px dashed var(--rule);
  border-radius: 8px;
  color: var(--ink-mute);
}

// ── Try it yourself ───────────────────────────────────────────────────────
.trial-section {
  padding: 28px 32px;
  border: 1px solid var(--rule);
  border-radius: 8px;
  background: var(--paper-2);
}
.trial-heading {
  font-family: var(--font-display);
  font-size: 22px;
  letter-spacing: -0.02em;
  color: var(--ink);
  margin: 0 0 4px;
}
.trial-badge {
  padding: 4px 12px;
  border: 1px solid var(--rule);
  border-radius: 4px;
  color: var(--ink-soft);
}
.mode-fixed {
  font-family: var(--font-mono);
  font-size: 12px;
  letter-spacing: 0.04em;
  text-transform: lowercase;
  padding: 4px 14px;
  border-radius: 999px;
  background: var(--q-primary);
  color: #fff;
}

.exhausted-banner {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 16px 20px;
  background: var(--paper);
  border: 1px solid var(--rule-strong);
  border-radius: 6px;
  font-size: 14px;
  color: var(--ink);
  font-weight: 500;
}

// ── access-request form ───────────────────────────────────────────────────
.access-request-form {
  width: 100%;
  margin-top: 12px;
  display: flex;
  flex-direction: column;
}
.access-request-input {
  width: 100%;
}
.access-request-sent {
  width: 100%;
  margin-top: 12px;
  color: var(--ink-soft);
  line-height: 1.5;
}

// ── responsive ────────────────────────────────────────────────────────────
@media (max-width: 1199px) {
  .wb-grid {
    grid-template-columns: 1fr;
    gap: 24px;
  }
}
</style>
