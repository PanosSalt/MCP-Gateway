// Central home for frontend constants.
// Import from here instead of duplicating values across files.

/** Milliseconds before an in-flight API request is aborted. */
export const REQUEST_TIMEOUT_MS = 30_000

/** Maximum number of retry attempts for idempotent requests. */
export const MAX_RETRIES = 3

/** Base delay (ms) for exponential back-off between retries. */
export const RETRY_BASE_MS = 500

/** Window features string for the SSO popup. */
export const SSO_POPUP_DIMENSIONS = 'width=500,height=700'
