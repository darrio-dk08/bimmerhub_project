# bimmerhub_project

## Bugs and fixes

The following issues were encountered during development and deployment.
Test counts refer to the stage when each issue was resolved.

| Issue | Cause or finding | Resolution | Verification |
| --- | --- | --- | --- |
| Homepage returned 404 and `core:home` could not be reversed. | The core routes were not registered in the active project URL configuration. | Connected the core URL configuration and implemented the homepage view and template. | All four homepage tests passed. |
| Parts catalogue returned 404 and the `parts` namespace was missing. | The catalogue routes had not yet been connected. A subsequent URL configuration error also prevented Django from loading valid patterns. | Corrected `parts/urls.py` and included it in the project URL configuration. | All nine core and catalogue tests passed. |
| Product-detail tests could not run because of an `IndentationError`. | `PartDetailTests` was incorrectly nested and its class body was not indented correctly. | Moved the test class to module level and corrected its indentation. | Django discovered and ran all six detail tests. |
| Product-detail URLs could not be reversed and returned 404. | The detail route had not yet been implemented when its tests were introduced. | Added the detail route, view, template and catalogue links. | All 15 core and parts tests passed. |
| Homepage hero image was not found. | `core/images/home-hero.jpg` was unavailable at the expected static-file path. | Added the image at the expected location. | `findstatic` located the image; the responsive appearance was checked manually. |
| Initial Heroku migration command failed. | The Heroku CLI interpreted Django's `--noinput` argument as its own option. Database queries then failed because the tables did not exist. | Quoted the remote command: `heroku run --app bimmerhub-dk08 "python manage.py migrate --noinput"`. | All migrations completed successfully. The catalogue import was subsequently verified as 12 categories and 20 products. |
| Live admin login returned a CSRF 403 response. | The exact cause was not confirmed. A stale form or browser cookie was suspected. | Retried login in a fresh private browsing session without disabling CSRF protection. | Login succeeded and the Django administration dashboard appeared. |
| Three basket tests failed with a missing `DELIVERY_CHARGE` setting. | The active local settings did not expose the delivery-charge setting. | Ensured `DELIVERY_CHARGE = "30.00"` was saved at module level, outside the production-only block. | The Django shell reported `30.00`; all 52 tests passed and `git diff --check` reported no whitespace errors. |

| Checkout did not clear outdated basket entries when every product had been deleted. | The empty-basket check ran before deleted-product cleanup. | Moved deleted-product cleanup before the empty-basket check. | The regression test passed; all 67 tests passed. |

| Two Stripe retry tests failed while comparing mocked requests. | Copying the mock call object produced `call.__deepcopy__(...)` rather than a snapshot of its arguments. | Copied and compared `.args` and `.kwargs` separately. | Both retry tests passed; the full suite passed with 103 tests. |
| Stripe Checkout tests could not be imported after editing a test method. | The final test's definition had eight leading spaces instead of four, incorrectly nesting it inside the preceding test. | Aligned the method definition with the other test methods. | Python compilation succeeded and all nine Stripe Checkout service tests passed. |

Some initial failing tests were written before their corresponding features
were implemented. These are distinguished from regressions and configuration
errors in the descriptions above.

### Remaining work

The checkout address and order-review pages are implemented. Order creation
and Stripe test payments are not yet implemented. All 67 current automated
tests pass; this does not verify the unfinished payment features.