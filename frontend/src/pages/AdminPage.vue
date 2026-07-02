<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { useQuasar } from 'quasar';
import { useAuthStore } from 'src/stores/auth';
import { adminApi } from 'src/services/api';
import type { AdminUser, AdminAccessRequest } from 'src/services/api';

const $q = useQuasar();
const router = useRouter();
const authStore = useAuthStore();

// ── Gate ─────────────────────────────────────────────────────────────────────

const adminConfirmed = ref(false);

// ── Data ─────────────────────────────────────────────────────────────────────

const users = ref<AdminUser[]>([]);
const accessRequests = ref<AdminAccessRequest[]>([]);
const loadingUsers = ref(false);
const loadingRequests = ref(false);
const loadError = ref<string | null>(null);

// ── Invite by email ───────────────────────────────────────────────────────────

const inviteEmail = ref('');
const inviting = ref(false);

// ── Per-row invite (access requests) ─────────────────────────────────────────

const invitingRowId = ref<string | null>(null);

// ── User management (role + delete) ──────────────────────────────────────────

const SERVICE_EMAIL = 'service@aidetect.local';
const busyUserId = ref<string | null>(null);

// Self and the service account are not manageable from the UI (the backend
// enforces this too; here we just hide the controls).
function canManage(row: AdminUser): boolean {
  return row.id !== authStore.user?.id && row.email !== SERVICE_EMAIL;
}

async function handleSetRole(row: AdminUser, makeAdmin: boolean): Promise<void> {
  if (busyUserId.value) return;
  busyUserId.value = row.id;
  try {
    const updated = await adminApi.setRole(row.id, makeAdmin);
    const idx = users.value.findIndex((u) => u.id === row.id);
    if (idx !== -1) users.value[idx] = updated;
    $q.notify({
      message: makeAdmin ? `${row.email} is now an admin` : `Admin revoked for ${row.email}`,
      icon: 'check',
      color: 'positive',
    });
  } catch (err) {
    $q.notify({
      message: err instanceof Error ? err.message : 'Failed to update role',
      icon: 'error_outline',
      color: 'negative',
    });
  } finally {
    busyUserId.value = null;
  }
}

function handleDeleteUser(row: AdminUser): void {
  $q.dialog({
    title: 'Delete user',
    message: `Permanently delete ${row.email}? Their detections and share links are removed too. This cannot be undone.`,
    ok: { label: 'Delete', unelevated: true, noCaps: true, color: 'negative' },
    cancel: { label: 'Cancel', flat: true, noCaps: true },
  }).onOk(() => {
    void doDeleteUser(row);
  });
}

async function doDeleteUser(row: AdminUser): Promise<void> {
  if (busyUserId.value) return;
  busyUserId.value = row.id;
  try {
    await adminApi.deleteUser(row.id);
    users.value = users.value.filter((u) => u.id !== row.id);
    $q.notify({ message: `${row.email} deleted`, icon: 'check', color: 'positive' });
  } catch (err) {
    $q.notify({
      message: err instanceof Error ? err.message : 'Failed to delete user',
      icon: 'error_outline',
      color: 'negative',
    });
  } finally {
    busyUserId.value = null;
  }
}

// ── Table column definitions ──────────────────────────────────────────────────

const userColumns = [
  { name: 'email', label: 'Email', field: 'email', align: 'left' as const, sortable: true },
  { name: 'name', label: 'Name', field: 'name', align: 'left' as const, sortable: true },
  { name: 'role', label: 'Role', field: 'is_admin', align: 'left' as const },
  { name: 'joined', label: 'Joined', field: 'created_at', align: 'left' as const, sortable: true },
  { name: 'actions', label: '', field: 'id', align: 'right' as const },
];

const requestColumns = [
  { name: 'email', label: 'Email', field: 'email', align: 'left' as const, sortable: true },
  { name: 'status', label: 'Status', field: 'status', align: 'left' as const, sortable: true },
  {
    name: 'requested',
    label: 'Requested',
    field: 'created_at',
    align: 'left' as const,
    sortable: true,
  },
  { name: 'action', label: '', field: 'id', align: 'right' as const },
];

// Show every row instead of Quasar's 5-row default; the table body scrolls.
const usersPagination = ref({ rowsPerPage: 0 });
const requestsPagination = ref({ rowsPerPage: 0 });

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  } catch {
    return iso;
  }
}

// ── Data loading ──────────────────────────────────────────────────────────────

async function loadAll(): Promise<void> {
  loadError.value = null;
  loadingUsers.value = true;
  loadingRequests.value = true;
  try {
    const [u, r] = await Promise.all([adminApi.users(), adminApi.accessRequests()]);
    users.value = u;
    accessRequests.value = r;
  } catch (err) {
    loadError.value = err instanceof Error ? err.message : 'Failed to load admin data';
  } finally {
    loadingUsers.value = false;
    loadingRequests.value = false;
  }
}

// ── Actions ───────────────────────────────────────────────────────────────────

async function handleInviteByEmail(): Promise<void> {
  const email = inviteEmail.value.trim();
  if (!email || inviting.value) return;
  inviting.value = true;
  try {
    const res = await adminApi.invite(email);
    inviteEmail.value = '';
    $q.dialog({
      title: 'Invitation sent',
      message: res.url,
      ok: { label: 'Copy link', unelevated: true, noCaps: true, color: 'primary' },
      cancel: { label: 'Close', flat: true, noCaps: true },
    }).onOk(() => {
      void navigator.clipboard.writeText(res.url).then(() => {
        $q.notify({ message: 'Link copied', icon: 'content_copy', color: 'positive' });
      });
    });
    $q.notify({ message: `Invitation created for ${res.email}`, icon: 'check', color: 'positive' });
  } catch (err) {
    $q.notify({
      message: err instanceof Error ? err.message : 'Failed to create invitation',
      icon: 'error_outline',
      color: 'negative',
    });
  } finally {
    inviting.value = false;
  }
}

async function handleInviteRequest(row: AdminAccessRequest): Promise<void> {
  if (invitingRowId.value) return;
  invitingRowId.value = row.id;
  try {
    const res = await adminApi.inviteRequest(row.id);
    // The endpoint always marks the access request "invited" server-side; the
    // returned status is the *invitation's* (pending), not the request's — so
    // set 'invited' explicitly to hide the button immediately.
    const idx = accessRequests.value.findIndex((r) => r.id === row.id);
    if (idx !== -1) {
      accessRequests.value[idx] = { ...accessRequests.value[idx], status: 'invited' };
    }
    $q.dialog({
      title: 'Invitation sent',
      message: res.url,
      ok: { label: 'Copy link', unelevated: true, noCaps: true, color: 'primary' },
      cancel: { label: 'Close', flat: true, noCaps: true },
    }).onOk(() => {
      void navigator.clipboard.writeText(res.url).then(() => {
        $q.notify({ message: 'Link copied', icon: 'content_copy', color: 'positive' });
      });
    });
    $q.notify({
      message: `Invitation sent to ${res.email}`,
      icon: 'check',
      color: 'positive',
    });
  } catch (err) {
    $q.notify({
      message: err instanceof Error ? err.message : 'Failed to send invitation',
      icon: 'error_outline',
      color: 'negative',
    });
  } finally {
    invitingRowId.value = null;
  }
}

// ── Mount: auth + admin gate ──────────────────────────────────────────────────

onMounted(async () => {
  if (!authStore.isAuthenticated) {
    await router.replace('/login');
    return;
  }
  if (!authStore.user) {
    await authStore.fetchMe();
  }
  if (!authStore.user?.is_admin) {
    await router.replace('/');
    return;
  }
  adminConfirmed.value = true;
  await loadAll();
});
</script>

<template>
  <q-page v-if="adminConfirmed" data-testid="admin-page" class="admin-page">
    <div class="admin-wrap">
      <!-- ── Page header ── -->
      <div class="admin-header q-mb-xl">
        <span class="eyebrow">admin</span>
        <h1 class="admin-title">Panel</h1>
      </div>

      <!-- ── Load error ── -->
      <q-banner v-if="loadError" class="bg-red-1 text-red-10 q-mb-lg" rounded dense>
        <template #avatar><q-icon name="error_outline" /></template>
        {{ loadError }}
        <template #action>
          <q-btn flat no-caps label="Retry" @click="loadAll" />
        </template>
      </q-banner>

      <!-- ════════════════════════════════════════════════════════
           SECTION 1 — Users
      ════════════════════════════════════════════════════════ -->
      <section data-testid="admin-users" class="admin-section q-mb-xl">
        <div class="row items-baseline q-mb-md">
          <span class="eyebrow section-label">users</span>
          <q-space />
          <span class="eyebrow section-count font-mono">{{ users.length }}</span>
        </div>
        <div class="editorial-rule q-mb-md"></div>

        <q-table
          v-model:pagination="usersPagination"
          :rows="users"
          :columns="userColumns"
          row-key="id"
          :loading="loadingUsers"
          flat
          bordered
          dense
          hide-bottom
          class="admin-table admin-table--scroll"
        >
          <template #body-cell-role="{ row }">
            <q-td>
              <span v-if="row.is_admin" class="role-chip role-chip--admin eyebrow">admin</span>
              <span v-else class="role-chip role-chip--user eyebrow">user</span>
            </q-td>
          </template>

          <template #body-cell-name="{ row }">
            <q-td>{{ row.name ?? '—' }}</q-td>
          </template>

          <template #body-cell-joined="{ row }">
            <q-td class="font-mono">{{ formatDate(row.created_at) }}</q-td>
          </template>

          <template #body-cell-actions="{ row }">
            <q-td class="text-right">
              <template v-if="canManage(row)">
                <q-btn
                  :label="row.is_admin ? 'Revoke admin' : 'Make admin'"
                  flat
                  no-caps
                  size="sm"
                  :color="row.is_admin ? 'grey-8' : 'primary'"
                  :loading="busyUserId === row.id"
                  :disable="busyUserId !== null"
                  data-testid="role-toggle"
                  @click="handleSetRole(row, !row.is_admin)"
                />
                <q-btn
                  icon="delete_outline"
                  flat
                  round
                  size="sm"
                  color="negative"
                  :disable="busyUserId !== null"
                  data-testid="delete-user"
                  @click="handleDeleteUser(row)"
                />
              </template>
              <span v-else class="eyebrow text-grey-5">—</span>
            </q-td>
          </template>

          <template #no-data>
            <div class="admin-empty eyebrow">No users yet.</div>
          </template>
        </q-table>
      </section>

      <!-- ════════════════════════════════════════════════════════
           SECTION 2 — Access Requests
      ════════════════════════════════════════════════════════ -->
      <section data-testid="admin-access-requests" class="admin-section">
        <div class="row items-baseline q-mb-md">
          <span class="eyebrow section-label">access requests</span>
          <q-space />
          <span class="eyebrow section-count font-mono">{{ accessRequests.length }}</span>
        </div>
        <div class="editorial-rule q-mb-md"></div>

        <!-- Invite by email -->
        <div class="invite-form q-mb-lg">
          <span class="eyebrow q-mb-xs" style="display: block">invite by email</span>
          <div class="row q-gutter-sm items-start">
            <q-input
              v-model="inviteEmail"
              type="email"
              outlined
              dense
              placeholder="user@example.com"
              class="invite-email-input"
              :disable="inviting"
              @keyup.enter="handleInviteByEmail"
            />
            <q-btn
              label="Invite"
              unelevated
              no-caps
              color="primary"
              :loading="inviting"
              :disable="!inviteEmail.trim() || inviting"
              @click="handleInviteByEmail"
            >
              <template #loading><q-spinner-dots /></template>
            </q-btn>
          </div>
        </div>

        <q-table
          v-model:pagination="requestsPagination"
          :rows="accessRequests"
          :columns="requestColumns"
          row-key="id"
          :loading="loadingRequests"
          flat
          bordered
          dense
          hide-bottom
          class="admin-table admin-table--scroll"
        >
          <template #body-cell-status="{ row }">
            <q-td>
              <span
                class="status-chip eyebrow"
                :class="`status-chip--${row.status}`"
              >{{ row.status }}</span>
            </q-td>
          </template>

          <template #body-cell-requested="{ row }">
            <q-td class="font-mono">{{ formatDate(row.created_at) }}</q-td>
          </template>

          <template #body-cell-action="{ row }">
            <q-td class="text-right">
              <q-btn
                v-if="row.status === 'pending'"
                label="Invite"
                unelevated
                no-caps
                size="sm"
                color="primary"
                :loading="invitingRowId === row.id"
                :disable="invitingRowId !== null"
                @click="handleInviteRequest(row)"
              >
                <template #loading><q-spinner-dots /></template>
              </q-btn>
              <span v-else class="eyebrow text-grey-5">{{ row.status }}</span>
            </q-td>
          </template>

          <template #no-data>
            <div class="admin-empty eyebrow">No access requests yet.</div>
          </template>
        </q-table>
      </section>
    </div>
  </q-page>
</template>

<style scoped lang="scss">
.admin-page {
  padding: 40px 28px 80px;
  min-height: calc(100vh - 64px);
}

.admin-wrap {
  max-width: 1100px;
  margin: 0 auto;
}

.admin-header {
  .admin-title {
    font-family: var(--font-display);
    font-size: clamp(36px, 5vw, 56px);
    letter-spacing: -0.04em;
    line-height: 1.02;
    color: var(--ink);
    margin: 0;
  }
}

.admin-section {
  // intentionally unstyled container — structure comes from q-table + eyebrow labels
}

.section-label {
  font-size: 12px;
  letter-spacing: 0.08em;
  color: var(--ink-mute);
}

.section-count {
  font-size: 11px;
  color: var(--ink-mute);
  padding: 3px 7px;
  border-radius: 2px;
}

.editorial-rule {
  height: 1px;
  background: var(--rule);
}

// ── Table ────────────────────────────────────────────────────────────────────

.admin-table {
  :deep(th) {
    font-family: var(--font-mono);
    font-size: 11px;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--ink-mute);
    font-weight: 500;
  }
  :deep(td) {
    font-size: 13px;
    color: var(--ink);
  }
  :deep(.q-table__top),
  :deep(.q-table__bottom) {
    padding: 8px 16px;
  }
}

// Cap height and let the body scroll with a sticky header, so long lists stay
// fully reachable (the counter shows the true total).
.admin-table--scroll {
  max-height: 60vh;

  :deep(thead tr th) {
    position: sticky;
    top: 0;
    z-index: 1;
    background: var(--paper);
  }
}

.admin-empty {
  padding: 24px 16px;
  color: var(--ink-mute);
}

// ── Role chips ────────────────────────────────────────────────────────────────

.role-chip {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 2px;
  font-size: 11px;
  letter-spacing: 0.06em;

  &--admin {
    background: var(--accent);
    color: #fff;
  }

  &--user {
    background: var(--paper-2, #f5f5f5);
    color: var(--ink-mute);
    border: 1px solid var(--rule);
  }
}

// ── Status chips ──────────────────────────────────────────────────────────────

.status-chip {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 2px;
  font-size: 11px;
  letter-spacing: 0.06em;
  text-transform: lowercase;

  &--pending {
    background: #fff8e1;
    color: #795548;
    border: 1px solid #ffe082;
  }

  &--invited {
    background: #e8f5e9;
    color: #2e7d32;
    border: 1px solid #a5d6a7;
  }
}

// ── Invite form ───────────────────────────────────────────────────────────────

.invite-form {
  background: var(--paper-2, #f9f9f9);
  border: 1px solid var(--rule);
  border-radius: 6px;
  padding: 16px 20px;
}

.invite-email-input {
  min-width: 280px;
}

// ── Responsive ────────────────────────────────────────────────────────────────

@media (max-width: 700px) {
  .admin-page {
    padding: 24px 16px 64px;
  }

  .invite-email-input {
    min-width: 0;
    width: 100%;
  }

  .invite-form .row {
    flex-direction: column;
  }
}
</style>
