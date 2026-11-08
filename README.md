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

### Remaining work

The review page's payment button still needs to connect the browser
checkout journey to the reservation and Stripe Checkout services.

A successful sandbox payment through the website and the complete
browser checkout journey remain to be tested.

The latest local payment changes have not yet been deployed to Heroku.
The README will be expanded with setup, deployment and further testing
instructions as development continues.

## Testing

### Automated tests

The latest local test run passed all 148 tests:

```powershell
python manage.py test core accounts parts garage payments
```

The test run reported no Django system-check issues.
`git diff --check` reported no whitespace errors.

Payment tests include mocked Stripe responses, conversion of actual
Stripe SDK objects and signed webhook payloads. Passing these tests
does not replace testing the complete payment journey against Stripe's
sandbox.

### Manual Stripe sandbox expiry test

Created a local test order and a real Stripe sandbox Checkout Session,
then expired the session through Stripe's API while the local webhook
listener and Django server were running.

Verified:

- Stripe sent `checkout.session.expired`.
- The local `/basket/webhook/` endpoint returned HTTP 200.
- The order became `cancelled`.
- `stock_reserved` became `False`.
- Product stock returned from 1 to 2.
- `paid_at` remained `None`.

This verifies the sandbox expiry and stock-release flow. Successful
payment and the complete browser checkout journey remain to be tested.