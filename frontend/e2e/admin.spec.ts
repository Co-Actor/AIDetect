import { test, expect } from '@playwright/test';

// Fixed admin email — the backend must be started with ADMIN_EMAILS including this address.
const ADMIN_EMAIL = 'e2e-admin@example.com';
const ADMIN_PASSWORD = 'testpassword123';
const BACKEND = 'http://localhost:8010';

// ── helpers ──────────────────────────────────────────────────────────────────

async function obtainAdminInviteToken(email: string): Promise<string> {
  const internalToken = process.env.AIDETECT_INTERNAL_TOKEN ?? '';
  const res = await fetch(`${BACKEND}/v1/admin/invitations`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-API-Key': internalToken,
    },
    body: JSON.stringify({ email }),
  });
  if (!res.ok) {
    throw new Error(`Admin invitation failed: ${res.status} ${await res.text()}`);
  }
  const data = (await res.json()) as { token: string };
  return data.token;
}

async function seedAccessRequest(email: string): Promise<string> {
  const res = await fetch(`${BACKEND}/v1/access-requests`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  });
  if (!res.ok) {
    throw new Error(`Access request seed failed: ${res.status} ${await res.text()}`);
  }
  const data = (await res.json()) as { id?: string };
  return data.id ?? '';
}

// ── test ─────────────────────────────────────────────────────────────────────

test('admin panel: login, view users/requests, invite from request row', async ({ page }) => {
  // Unique requester email so the row is fresh on each run.
  const requesterEmail = `wants+${Date.now()}@example.com`;

  // 1. Seed: admin invite + an access request.
  const adminToken = await obtainAdminInviteToken(ADMIN_EMAIL);
  await seedAccessRequest(requesterEmail);

  // 2. Register the admin user via the invite link.
  await page.goto(`/register?invite=${adminToken}`);
  // The email field is pre-filled and disabled — only fill password.
  await page.getByTestId('register-password').fill(ADMIN_PASSWORD);
  await page.getByTestId('register-submit').click();

  // After successful registration the app redirects to the workbench.
  await expect(page).toHaveURL('/', { timeout: 10_000 });
  await expect(page.getByText(/spot the/i)).toBeVisible({ timeout: 8_000 });

  // 3. Open the user dropdown and verify the Admin link is visible.
  // The dropdown trigger label is the user's email.
  await page.getByRole('button', { name: ADMIN_EMAIL }).click();
  const adminLink = page.getByTestId('admin-link');
  await expect(adminLink).toBeVisible({ timeout: 5_000 });

  // 4. Navigate to /admin via the link.
  await adminLink.click();
  await expect(page).toHaveURL('/admin', { timeout: 8_000 });

  // 5. Admin page root is rendered.
  await expect(page.getByTestId('admin-page')).toBeVisible({ timeout: 8_000 });

  // 6. Both sections are present.
  await expect(page.getByTestId('admin-users')).toBeVisible();
  await expect(page.getByTestId('admin-access-requests')).toBeVisible();

  // 7. The seeded access request row appears in the table.
  await expect(page.getByText(requesterEmail)).toBeVisible({ timeout: 8_000 });

  // 8. Click the Invite button on the pending row.
  // There may be multiple rows; find the one for our requesterEmail.
  const requestRow = page.locator('tr', { hasText: requesterEmail });
  const inviteBtn = requestRow.getByRole('button', { name: 'Invite' });
  await expect(inviteBtn).toBeVisible();
  await inviteBtn.click();

  // 9. A success notification appears OR the row status changes away from "pending".
  // We check either: a Quasar notify message or the row no longer shows the Invite button.
  await expect(inviteBtn).toBeHidden({ timeout: 10_000 });
});
