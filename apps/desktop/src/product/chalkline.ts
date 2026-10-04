import { dismissFirstRunOnboarding } from '@/store/onboarding'

export const isChalklineProduct = import.meta.env.VITE_HERMES_PRODUCT_PROFILE === 'chalkline'

export function initializeChalklineProduct(): void {
  if (!isChalklineProduct || typeof document === 'undefined') {
    return
  }

  document.documentElement.dataset.productProfile = 'chalkline'
  document.title = 'Chalkline'

  // Chalkline is useful before a model provider is connected: planning,
  // evidence capture, roster import, and exports are all local workflows.
  // Keep provider setup available from the teacher agent, but never let OG
  // Hermes's first-run picker block the product workspace.
  dismissFirstRunOnboarding()

  const params = new URLSearchParams(window.location.search)

  if (params.has('win')) {
    return
  }

  if (!window.location.hash || window.location.hash === '#' || window.location.hash === '#/') {
    window.location.hash = '#/chalkline'
  }
}
