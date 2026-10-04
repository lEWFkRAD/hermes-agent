import { expect, it } from 'vitest'

import { desktopProductProtocol } from './product-protocol'

it('keeps Chalkline links isolated in packaged and development runs', () => {
  for (const development of [false, true]) {
    const result = desktopProductProtocol('com.onyxintelligence.chalkline', development)
    expect(result.protocol).toBe(development ? 'chalkline-dev' : 'chalkline')
    expect(result.accepted).toContain('chalkline')
    expect(result.accepted).not.toContain('hermes')
    expect(result.accepted).not.toContain('hermes-dev')
  }
})

it('preserves the standard Hermes link contract', () => {
  expect(desktopProductProtocol('com.nousresearch.hermes', false)).toEqual({
    protocol: 'hermes', accepted: ['hermes']
  })
  expect(desktopProductProtocol('com.nousresearch.hermes', true)).toEqual({
    protocol: 'hermes-dev', accepted: ['hermes-dev', 'hermes']
  })
})
