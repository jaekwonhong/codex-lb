# Change: Repair recipient effect-boundary validation

## Why
The recipient lifecycle must retain its exact identity and truthful effect evidence inside the browser-side action, not only before dispatch. Malformed Task Space observations must not be treated as absence.

## What changes
Bind recipient email and user ID at the personal and acceptance action boundary; validate the HTTPS ChatGPT origin; distinguish pre-dispatch session failure from acknowledged acceptance and uncertain server responses. Reject malformed Task Space collections before creation. Preserve general-login CDP compatibility, existing runtime releases and the original acceptance no-replay rule.
