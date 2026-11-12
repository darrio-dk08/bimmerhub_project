# Testing

[Return to README](README.md)

## HTML validation

Rendered pages were checked using the W3C Nu HTML Checker on
12 November 2026.

### Homepage

Result: no errors or warnings.

![Homepage HTML validation](<docs/testing/Screenshot 2026-11-12 195647.png>)

### Parts catalogue

![Parts catalogue HTML validation](<docs/testing/Screenshot 2026-11-12 195719.png>)

### Product-detail page

![Product-detail HTML validation](<docs/testing/Screenshot 2026-11-12 195744.png>)

### Login page

![Login page HTML validation](<docs/testing/Screenshot 2026-11-12 195817.png>)

### Registration page — initial errors

The initial check found four HTML errors caused by invalid nesting
around the password-help list.

![Registration page before the HTML fix](<docs/testing/Screenshot 2026-11-12 195859.png>)

### Registration page — recheck after the fix

The signup template was updated to render fields and help text in div
elements instead of using form.as_p. All 15 authentication regression
tests passed after the change.

![Registration page validation after the fix](<docs/testing/Screenshot 2026-11-12 203813.png>)

### Basket page

![Basket page HTML validation](<docs/testing/Screenshot 2026-11-12 203909.png>)