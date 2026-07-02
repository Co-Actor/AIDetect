import { test, expect, type Page, type BrowserContext } from '@playwright/test';

// Unique email per run so the test can be re-run without conflicts.
const uniqueEmail = `auth+${Date.now()}@example.com`;
const testPassword = 'testpassword123';

// --- helpers ---------------------------------------------------------------

async function obtainInviteToken(email: string): Promise<string> {
  // Call the admin API to create an invitation for the test user.
  const internalToken = process.env.AIDETECT_INTERNAL_TOKEN ?? '';
  const res = await fetch('http://localhost:8010/v1/admin/invitations', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-API-Key': internalToken,
    },
    body: JSON.stringify({ email }),
  });
  if (!res.ok) {
    throw new Error(`Admin invitation request failed: ${res.status} ${await res.text()}`);
  }
  const data = (await res.json()) as { token: string };
  return data.token;
}

async function fillAndSubmitRegister(page: Page, token: string): Promise<void> {
  await page.goto(`/register?invite=${token}`);
  // Email is prefilled and disabled — only fill the password.
  await page.getByTestId('register-password').fill(testPassword);
  await page.getByTestId('register-submit').click();
}

async function waitForWorkbench(page: Page): Promise<void> {
  // After successful registration the app redirects to the workbench (/).
  await expect(page).toHaveURL('/', { timeout: 10_000 });
  // The workbench headline is always present.
  await expect(page.getByText(/spot the/i)).toBeVisible({ timeout: 8_000 });
}

async function analyzeText(page: Page, inputText: string): Promise<void> {
  await page.getByPlaceholder(/paste a text/i).fill(inputText);
  await page.getByTestId('analyze-btn').click();
  // Wait until the gauge/verdict is visible — the spinner will disappear first.
  await expect(page.getByText(/human score/i)).toBeVisible({ timeout: 30_000 });
}

// --- test ------------------------------------------------------------------

test('register → analyze → share → shared page → trial × 3 → exhausted → request access', async ({
  browser,
  request: _request,
}) => {
  // ── Obtain invitation via admin API ───────────────────────────────────────
  const inviteToken = await obtainInviteToken(uniqueEmail);

  // ── Context 1: authenticated user ────────────────────────────────────────
  const authContext: BrowserContext = await browser.newContext();
  const page: Page = await authContext.newPage();

  // 1. Register via invite link
  await fillAndSubmitRegister(page, inviteToken);
  await waitForWorkbench(page);

  // 2. Analyze
  const sampleText =
    'In the rapidly evolving landscape of artificial intelligence, ' +
    'it is crucial to leverage synergies across multiple verticals. ' +
    'By harnessing cutting-edge machine learning paradigms, organizations ' +
    'can unlock unprecedented value and drive transformative outcomes. ' +
    'This holistic approach ensures seamless integration of diverse skill sets, ' +
    'fostering a culture of innovation and excellence.';

  await analyzeText(page, sampleText);

  // 3. Click Share
  await page.getByTestId('share-btn').click();

  // Dialog appears with the share URL in its message body.
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible({ timeout: 8_000 });

  // Capture the share URL from the dialog message text.
  const dialogText = await dialog.innerText();
  const urlMatch = dialogText.match(/https?:\/\/[^\s]+\/r\/[^\s]+/);
  if (!urlMatch) throw new Error(`Share URL not found in dialog: ${dialogText}`);
  const shareUrl = urlMatch[0].trim();

  // Extract just the path portion for use in the second context.
  const sharePath = new URL(shareUrl).pathname;

  // Close the dialog by clicking Cancel/Close.
  await page.getByRole('button', { name: /close/i }).click();

  // ── Context 2: anonymous visitor ─────────────────────────────────────────
  const anonContext: BrowserContext = await browser.newContext();
  const anonPage: Page = await anonContext.newPage();

  await anonPage.goto(sharePath);

  // The shared result should be visible.
  await expect(anonPage.getByText(/human score/i)).toBeVisible({ timeout: 15_000 });
  // Verdict or gauge visible.
  await expect(anonPage.getByText(/verdict/i)).toBeVisible();

  // ── Trial: run 3 times, gated on the server-side counter ─────────────────
  // The "Free checks left" badge only changes when a trial response arrives, so
  // it is the deterministic signal that one trial actually completed. (Waiting on
  // the result view is unreliable: the shared result already shows "human score",
  // so the assertion would pass instantly and fire the next click mid-request.)
  const trialTexts = [
    'The weather today is quite pleasant for a walk in the park.',
    'I really enjoy cooking pasta with homemade tomato sauce on weekends.',
    'Our team worked hard to deliver the project ahead of schedule.',
  ];

  // Initial state: 3 free checks, no banner.
  await expect(anonPage.getByTestId('trial-remaining')).toHaveText('3');
  await expect(anonPage.getByTestId('exhausted-banner')).toBeHidden();

  let trialIndex = 0;
  for (const trialInput of trialTexts) {
    // After a completed trial "your text" switches to the annotated view (like the
    // product). Clear it to get the editable textarea back before the next check.
    if (trialIndex > 0) {
      await anonPage.getByTestId('trial-clear').click();
    }
    await anonPage.getByTestId('trial-textarea').fill(trialInput);
    await anonPage.getByTestId('trial-analyze-btn').click();

    if (trialIndex < trialTexts.length - 1) {
      // Counter must decrement (2, then 1) before the next trial fires.
      await expect(anonPage.getByTestId('trial-remaining')).toHaveText(String(2 - trialIndex), {
        timeout: 30_000,
      });
    }
    trialIndex++;
  }

  // After the 3rd trial the link is exhausted: banner with the English message.
  await expect(anonPage.getByTestId('exhausted-banner')).toBeVisible({ timeout: 30_000 });
  await expect(anonPage.getByTestId('exhausted-banner')).toContainText(
    "You've used all 3 free checks. Sign up to keep using AIDetect.",
  );

  // Regression guard: the 3rd (last) result must STAY visible next to the banner.
  // "your result" only renders when the trial result panel is shown, so this fails
  // if the result gets hidden the moment the quota hits zero (the reported bug).
  await expect(anonPage.getByText(/your result/i)).toBeVisible();

  // ── Request-access form is shown instead of a Register button ─────────────
  await expect(anonPage.getByTestId('request-email')).toBeVisible();

  const requestEmailAddress = `access+${Date.now()}@example.com`;
  await anonPage.getByTestId('request-email').fill(requestEmailAddress);
  await anonPage.getByTestId('request-submit').click();

  // Confirmation message should appear.
  await expect(anonPage.getByTestId('request-sent')).toBeVisible({ timeout: 10_000 });
  await expect(anonPage.getByTestId('request-sent')).toContainText(
    `Thanks — we'll email an invitation to ${requestEmailAddress}.`,
  );

  // ── Cleanup ───────────────────────────────────────────────────────────────
  await authContext.close();
  await anonContext.close();
});
