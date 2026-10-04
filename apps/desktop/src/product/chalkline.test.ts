import { afterEach, expect, it, vi } from 'vitest'

const { dismiss } = vi.hoisted(() => ({ dismiss: vi.fn() }))
vi.mock('@/store/onboarding', () => ({ dismissFirstRunOnboarding: dismiss }))

afterEach(() => {
  vi.unstubAllEnvs()
  vi.resetModules()
  vi.clearAllMocks()
  window.history.replaceState(null, '', '/')
  delete document.documentElement.dataset.productProfile
})

it('opens the teacher workspace before provider setup on a fresh launch', async () => {
  vi.stubEnv('VITE_HERMES_PRODUCT_PROFILE', 'chalkline')
  const { initializeChalklineProduct } = await import('./chalkline')
  initializeChalklineProduct()
  expect(window.location.hash).toBe('#/chalkline')
  expect(document.title).toBe('Chalkline')
  expect(dismiss).toHaveBeenCalledOnce()
})

it('preserves an explicit classroom route and leaves secondary window routing alone', async () => {
  vi.stubEnv('VITE_HERMES_PRODUCT_PROFILE', 'chalkline')
  const { initializeChalklineProduct } = await import('./chalkline')
  window.history.replaceState(null, '', '/#/chalkline/evidence')
  initializeChalklineProduct()
  expect(window.location.hash).toBe('#/chalkline/evidence')
  window.history.replaceState(null, '', '/?win=secondary#/')
  initializeChalklineProduct()
  expect(window.location.hash).toBe('#/')
})
