# BimmerHub

BimmerHub is a Django application for browsing BMW parts, managing a
personal vehicle garage and ordering parts for delivery within Ireland.
Delivery is charged at a fixed rate of €30 per order.

The payment integration is currently being developed and tested using
Stripe's sandbox.

## Bugs and fixes

The following issues were encountered during development and deployment.
Test counts refer to the stage when each issue was resolved.

| Issue | Cause or finding | Resolution | Verification |
| --- | --- | --- | --- |
| Homepage returned 404 and `core:home` could not be reversed. | The core routes were not registered in the active project URL configuration. | Connected the core URL configuration and implemented the homepage view and template. | All four homepage tests passed. |
| Parts catalogue returned 404 and the `parts` namespace was missing. | Catalogue routes had not been connected. A subsequent URL configuration error also prevented Django from loading valid patterns. | Corrected `parts/urls.py` and included it in the project URL configuration. | All nine core and catalogue tests passed. |
| Product-detail tests could not run because of an `IndentationError`. | `PartDetailTests` was incorrectly nested and its class body was not indented correctly. | Moved the test class to module level and corrected its indentation. | Django discovered and ran all six detail tests. |
| Product-detail URLs could not be reversed and returned 404. | The detail route had not yet been implemented when its tests were introduced. | Added the detail route, view, template and catalogue links. | All 15 core and parts tests passed. |
| Homepage hero image was not found. | `core/images/home-hero.jpg` was unavailable at the expected static-file path. | Added the image at the expected location. | `findstatic` located the image; the responsive appearance was checked manually. |
| Initial Heroku migration command failed. | The Heroku CLI interpreted Django's `--noinput` argument as its own option. Database queries then failed because the tables did not exist. | Quoted the remote command: `heroku run --app bimmerhub-dk08 "python manage.py migrate --noinput"`. | Migrations completed successfully. The subsequent catalogue import was verified as 12 categories and 20 products. |
| Live admin login returned a CSRF 403 response. | The exact cause was not confirmed. A stale form or browser cookie was suspected. | Retried login in a fresh private browsing session without disabling CSRF protection. | Login succeeded and the Django administration dashboard appeared. |
| Three basket tests failed with a missing `DELIVERY_CHARGE` setting. | The active local settings did not expose the delivery-charge setting. | Saved `DELIVERY_CHARGE = "30.00"` at module level, outside the production-only block. | The Django shell reported `30.00`; all 52 tests passed. |
| Checkout did not clear outdated basket entries when every product had been deleted. | The empty-basket check ran before deleted-product cleanup. | Moved deleted-product cleanup before the empty-basket check. | The regression test passed; all 67 tests passed. |
| Two Stripe retry tests failed while comparing mocked requests. | Copying the mock call object produced `call.__deepcopy__(...)` rather than a snapshot of its arguments. | Copied and compared `.args` and `.kwargs` separately. | Both retry tests passed; all 103 tests passed. |
| Stripe Checkout tests could not be imported after editing a test method. | The final test's definition had eight leading spaces instead of four, incorrectly nesting it inside the preceding test. | Aligned the method definition with the other test methods. | Python compilation succeeded and all nine Stripe Checkout service tests passed. |
| Stripe webhook processing raised `AttributeError: get`. | Stripe Python v15 response objects did not support the dictionary-style access used by the code. Earlier dictionary-based mocks concealed the incompatibility. | Added a shared conversion helper using `to_dict()` and applied it to webhook and payment-service responses. Corrected a missing helper import during verification. | Tests using an actual SDK object and signed webhook payloads passed; all 138 tests passed. |
| Lint checks reported incorrect indentation, an unused import, trailing spaces and missing final newlines. | The Stripe exception block was over-indented, an unused test import remained, and several files had formatting issues. An attempted indentation correction also misaligned `except` with `try`. | Replaced the complete exception-handling block, removed the unused import, stripped trailing whitespace and added final newlines. | All 148 tests passed, `git diff --check` was clean, and VS Code showed no remaining problems after reloading. |

Some initial failing tests were written before their corresponding features
were implemented. These are distinguished from regressions and
configuration errors in the descriptions above.

## Current development status

Implemented locally:

- Parts catalogue and product-detail pages.
- Account registration, login and logout pages.
- Personal garage management.
- Session basket with quantity and stock validation.
- Ireland-only checkout address form and order review.
- Fixed €30 delivery charge.
- Order and order-item models with saved product details and prices.
- Pending-order creation and stock reservation.
- Protection against repeated checkout submissions at service level.
- Stripe sandbox Checkout session creation and retry handling.
- Payment verification and signed webhook processing.
- Recovery of missing Stripe session links.
- Stock release after verified unpaid session expiry.
- Customer-owned payment return pages.

### Browser payment connection

The order-review page now has a Continue to payment button. The application
stores reviewed quantities, individual prices, delivery and address in the
customer's session. Before committing a reservation, it compares the saved
order against those reviewed amounts. A mismatch rolls back the order and
stock deduction and requires another review.

Repeated submissions reuse the order token and Stripe idempotency key.
An existing pending reservation is shown before another browser checkout
can create an order. Resume payment uses the original saved order prices.

Payment status pages offer a POST-only resume action and, when a Stripe
session is known, a POST-only cancellation action. Returning through the
cancel URL alone does not cancel the order. Stock is restored only after
Stripe expiry is verified. Paid orders are not released.

After payment confirmation, the original basket is cleared only if it has
not been edited since review. Later basket changes are preserved. Refreshing
an old confirmation page does not clear a newly filled basket.

### Remaining work

Successful sandbox payment, preservation of a new basket when revisiting
a confirmation page, resuming an unpaid checkout and browser cancellation
have all been manually verified locally.

An old payment attempt whose Stripe session ID is still unknown requires
reconciliation/support. The application keeps its reservation rather than
assuming a timeout means that Stripe created no session. Automatic scheduled
reconciliation of abandoned attempts has not been implemented.

These local payment changes have not yet been deployed to Heroku. The README
will be expanded with setup, deployment and further testing instructions.

## Testing

### Automated tests

All 175 automated tests passed locally on Windows using Python 3.11.
The same suite also passed in an isolated Python 3.12 environment using
the project's pinned dependencies, Django 5.2.14 and Stripe Python 15.1.0.
```powershell
python manage.py test core accounts parts garage payments
```

There are 27 new browser-connection tests. They exercise the real order,
reservation and payment services through Django's test client, replacing only
Stripe's network client with mocks returning actual Stripe SDK objects.
They cover reviewed-price changes, delivery changes, stock rollback, forged
form values, retries, ownership, CSRF, cancellation and basket preservation.
The existing payment-return tests also mock the expiry verification boundary.

The tests use SQLite. They do not establish PostgreSQL concurrency behaviour
under simultaneous load, and they do not replace a real sandbox browser test.
No real Stripe API requests or payments were made by the automated suite.

### Manual Stripe sandbox expiry test

This verifies the sandbox expiry and stock-release flow. Successful
browser payment, repeat visits, resume and cancellation were also
verified, as recorded below.

Verified:

- Stripe sent `checkout.session.expired`.
- The local `/basket/webhook/` endpoint returned HTTP 200.
- The order became `cancelled`.
- `stock_reserved` became `False`.
- Product stock returned from 1 to 2.
- `paid_at` remained `None`.

This verifies the sandbox expiry and stock-release flow. A successful
browser payment was also verified, as recorded below. Manual browser
cancellation and repeat-visit checks remain outstanding.

### Manual successful Stripe sandbox payment

Verified locally on 8 November 2026:

- Continued from the order-review page to Stripe Checkout.
- Stripe displayed the reviewed total, including €30 delivery.
- Completed payment using a Stripe sandbox test card.
- The checkout.session.completed webhook returned HTTP 200.
- BimmerHub displayed Payment confirmed with the correct total.
- The original basket was empty after confirmation.

All 175 automated tests also passed locally on Windows.

### Manual payment-confirmation repeat-visit test

After a successful sandbox payment, added a new product to the basket
in another tab and refreshed the original payment-confirmation page.

Verified that the new basket item remained. Revisiting the confirmation
page did not clear the new basket.

### Manual resume and cancellation tests

Verified locally on 9 November 2026:

- Returned from Stripe without paying.
- Resume this payment reopened Checkout with the same product,
  quantity and total.
- Cancel this unpaid order displayed Order cancelled.
- Stripe sent checkout.session.expired and the webhook returned HTTP 200.
- Basket items remained after cancellation.
- The saved order had status cancelled, stock_reserved False
  and paid_at None.
- The cancelled order contained two headlights; current product stock
  was four. No pre-checkout stock count was recorded for this test,
  so the exact stock increase was not independently measured.

  ### Customer order history

Customers can view their own orders through My orders and open saved
order details, including product prices, quantities, delivery and totals.
Automated tests cover ownership restrictions and saved order details.

Verified locally on Windows on 9 November 2026:

- All 191 automated tests passed.
- Previous orders appeared newest first.
- Order details displayed the correct products, quantities and totals.
- Paid and cancelled orders did not offer payment controls.
- Order-list and detail pages displayed correctly at desktop and mobile widths.

### Read-only order administration

Authorised staff can inspect orders in Django admin, search by order
reference or customer email, and filter by payment status.

Order details and saved product snapshots are read-only. Adding, editing
and deleting orders through admin are blocked, including for superusers.
Payment and stock changes remain handled by the payment services.

Verified locally on Windows on 9 November 2026:

- All 203 automated tests passed, including 12 order-admin tests.
- Order search and status filters worked correctly.
- Saved products, quantities, delivery, totals and status displayed correctly.
- Order fields could not be edited.
- Add order, Save and Delete controls were unavailable.