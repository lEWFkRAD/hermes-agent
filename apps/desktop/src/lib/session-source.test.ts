import { describe, expect, it } from 'vitest'

import { isMessagingSource, MESSAGING_SESSION_SOURCE_IDS, sessionSourceLabel } from './session-source'

describe('session source helpers', () => {
  // Regression: the per-platform sidebar refactor (#42537) introduced a
  // hardcoded allowlist that omitted the local platform adapters (kindle,
  // excel). Their sessions are recorded in state.db but were filtered out of
  // the messaging fetch by isMessagingSource(), so they vanished from the
  // sidebar. Keep these adapters first-class.
  it('treats Kindle as a first-class messaging sidebar source', () => {
    expect(isMessagingSource('kindle')).toBe(true)
    expect(MESSAGING_SESSION_SOURCE_IDS).toContain('kindle')
    expect(sessionSourceLabel('kindle')).toBe('Kindle')
  })

  it('treats Excel as a first-class messaging sidebar source', () => {
    expect(isMessagingSource('excel')).toBe(true)
    expect(MESSAGING_SESSION_SOURCE_IDS).toContain('excel')
    expect(sessionSourceLabel('excel')).toBe('Excel')
  })
})
