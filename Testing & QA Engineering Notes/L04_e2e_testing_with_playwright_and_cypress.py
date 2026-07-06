# ============================================================
# L04: End-to-End Testing with Playwright and Cypress
# ============================================================
# WHAT: How to test an application through its REAL, complete user
#       interface — the top of L01's test pyramid — using modern browser
#       automation tools, and the specific techniques that keep E2E
#       tests from becoming the flaky, unmaintainable liability they're
#       infamous for.
# WHY: L01-L03 covered unit and integration testing. E2E tests occupy a
#      genuinely necessary but historically PROBLEMATIC role — this
#      lesson covers how modern tools (Playwright, Cypress) and
#      practices address E2E testing's classic reliability problems.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
E2E TESTS drive a REAL browser through a REAL user flow (clicking
buttons, filling forms, navigating pages) against a running instance of
the application — this is the ONLY test type that verifies the ENTIRE
system (frontend, backend, database, and their actual integration) works
together from an actual user's perspective, which is exactly why L01
positions it at the pyramid's top despite its cost.

WHY E2E TESTS ARE HISTORICALLY FLAKY: the classic failure mode is a
RACE CONDITION between the test and the application — a test clicks a
button and immediately tries to assert on the result, but the
application hasn't finished its async operation (an API call, a
re-render) yet, causing an INTERMITTENT failure that has nothing to do
with an actual bug. Older tools (Selenium, without careful discipline)
required developers to manually add explicit waits/sleeps, which are
BOTH unreliable (a fixed wait might still be too short under load, or
unnecessarily slow the test down when the app responds fast) and a
primary source of E2E test flakiness historically.

PLAYWRIGHT AND CYPRESS'S KEY IMPROVEMENT — AUTO-WAITING: both tools
built in AUTOMATIC WAITING for elements to be actionable (visible,
enabled, stable — not animating) before interacting with them, and
automatic RETRYING of assertions until they pass or a timeout is
reached — this eliminates the NEED for most manual sleep/wait
statements, directly addressing the primary historical cause of E2E
flakiness. This is a genuinely significant reliability improvement over
older tools that required developers to get this right manually every time.

TEST ISOLATION for E2E tests requires deliberate design: each test
should set up its OWN required state (e.g. via API calls or database
seeding BEFORE the test, not depending on UI interactions from a
PREVIOUS test) and clean up afterward — tests that depend on
running in a specific ORDER (test 2 assumes test 1 already created a
user) are fragile and prevent PARALLELIZATION (a genuine speed benefit
both tools support, but only when tests are properly isolated from each other).

PAGE OBJECT MODEL (POM) is a maintainability pattern: rather than
scattering raw CSS/XPath selectors throughout test files, ENCAPSULATE a
page's structure and interactions behind a dedicated class — if the
UI's structure changes (a button's selector changes), you update ONE
page-object class rather than every test file that happened to click that button.

WHAT SHOULD (AND SHOULDN'T) BE AN E2E TEST: per L01's pyramid guidance,
E2E tests should cover the CRITICAL, HIGH-VALUE user journeys (can a
user sign up, can a user complete a purchase) — NOT every possible edge
case or validation rule, which are far better and more cheaply covered
by unit tests directly on the validation logic.

PRODUCTION USE CASE:
An e-commerce platform's E2E suite (using Playwright) covers exactly
5-10 critical flows — successful checkout, failed payment handling,
account creation — using a Page Object Model for maintainability and
API-based test-data setup (creating a test user via a direct API call
rather than clicking through a signup form first) to keep each test
fast and independent — while the hundreds of individual form-validation
rules and pricing-calculation edge cases are covered by fast unit tests instead.

COMMON MISTAKES:
- Adding manual `sleep()`/wait calls out of habit even with tools that
  auto-wait — this reintroduces the EXACT flakiness/slowness problem
  auto-waiting was built to solve, either making tests unnecessarily
  slow (over-long fixed waits) or still occasionally flaky (waits that
  are sometimes too short under different load conditions).
- Writing E2E tests that depend on a SPECIFIC EXECUTION ORDER or shared,
  mutating state from other tests — this prevents parallelization and
  makes failures hard to reproduce/debug in isolation, since a failure
  might depend on which OTHER tests ran before it.
- Trying to achieve high E2E coverage of every possible edge case — per
  L01's pyramid guidance, this inverts the pyramid, creating a slow,
  brittle suite for coverage that fast unit tests could provide far more cheaply and reliably.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Auto-waiting — the key reliability improvement
# ------------------------------------------------------------------
OLD_MANUAL_WAIT_EXAMPLE = textwrap.dedent("""\
    // OLD approach (Selenium-style, without careful auto-wait discipline):
    driver.find_element(By.ID, "submit-button").click()
    time.sleep(2)  // hope 2 seconds is enough for the async response...
    result = driver.find_element(By.ID, "result").text
    assert result == "Success"
    // FLAKY: too short under load, wastefully slow when the app responds fast
""")

PLAYWRIGHT_AUTO_WAIT_EXAMPLE = textwrap.dedent("""\
    // Playwright (auto-waiting built in):
    await page.click("#submit-button")
    // Playwright automatically WAITS for the element to be actionable
    // before clicking, and automatically RETRIES the following assertion
    // until it passes or times out — no manual sleep needed:
    await expect(page.locator("#result")).toHaveText("Success")
    // RELIABLE: waits exactly as long as needed, no more, no less
""")

# ------------------------------------------------------------------
# 2. Page Object Model — maintainable selector encapsulation
# ------------------------------------------------------------------
POM_EXAMPLE = textwrap.dedent("""\
    // WITHOUT Page Object Model — selectors scattered across test files
    test('checkout flow', async ({ page }) => {
      await page.click('#add-to-cart-btn');
      await page.click('.cart-icon');
      await page.click('[data-testid="checkout-submit"]');
      // If ANY of these selectors change, every test using them breaks
    });

    // WITH Page Object Model — selectors encapsulated in ONE place
    class ProductPage {
      constructor(page) { this.page = page; }
      async addToCart() { await this.page.click('#add-to-cart-btn'); }
    }
    class CheckoutPage {
      constructor(page) { this.page = page; }
      async submitOrder() { await this.page.click('[data-testid="checkout-submit"]'); }
    }

    test('checkout flow', async ({ page }) => {
      const productPage = new ProductPage(page);
      const checkoutPage = new CheckoutPage(page);
      await productPage.addToCart();
      await checkoutPage.submitOrder();
      // If the checkout button's selector changes, update ONLY CheckoutPage
    });
""")

# ------------------------------------------------------------------
# 3. Test isolation via API-based setup, not UI-driven setup
# ------------------------------------------------------------------
API_SETUP_EXAMPLE = textwrap.dedent("""\
    // SLOW, fragile: creating test state by clicking through the UI
    test('user can view their orders', async ({ page }) => {
      await page.goto('/signup');
      await page.fill('#email', 'test@example.com');
      // ... many more UI steps just to GET to the state we actually want to test
      await page.click('#place-order-button');
      // NOW finally test the actual thing we care about
    });

    // FAST, isolated: create required state via a direct API call
    test('user can view their orders', async ({ page, request }) => {
      const user = await request.post('/api/test/create-user');
      await request.post('/api/test/create-order', { data: { userId: user.id } });
      // Skip straight to what we're actually testing:
      await page.goto(`/orders?userId=${user.id}`);
      await expect(page.locator('.order-item')).toBeVisible();
    });
""")


if __name__ == "__main__":
    print(OLD_MANUAL_WAIT_EXAMPLE)
    print(PLAYWRIGHT_AUTO_WAIT_EXAMPLE)
    print(POM_EXAMPLE)
    print(API_SETUP_EXAMPLE)

"""
PRODUCTION CONTEXT EXAMPLE:
A team migrating from a Selenium-based E2E suite (plagued by ~20%
flaky-failure rates and heavy use of manual sleep statements) to
Playwright removes nearly all manual waits (relying on Playwright's
built-in auto-waiting and retrying assertions), refactors their tests
to use a Page Object Model (reducing the maintenance cost of the
frontend's frequent selector changes), and switches test setup from
UI-driven signup flows to direct API calls — the resulting suite runs
in a fraction of the time with a flaky-failure rate near zero, directly
attributable to addressing E2E testing's classic, well-understood failure modes.
"""
