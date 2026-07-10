import { describe, expect, it } from 'vitest'

import {
  isMessagingSource,
  MESSAGING_SESSION_SOURCE_IDS,
  sessionSourceLabel
} from './session-source'

describe('session source helpers', () => {
  it('treats Kindle as a first-class messaging sidebar source', () => {
    expect(isMessagingSource('kindle')).toBe(true)
    expect(sessionSourceLabel('kindle')).toBe('Kindle')
    expect(MESSAGING_SESSION_SOURCE_IDS).toContain('kindle')
  })
})
