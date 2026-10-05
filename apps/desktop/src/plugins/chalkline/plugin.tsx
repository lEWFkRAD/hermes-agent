import './chalkline.css'

import {
  type HermesPlugin,
  host,
  PALETTE_AREA,
  type PaletteContribution,
  type RouteContribution,
  ROUTES_AREA,
  SIDEBAR_NAV_AREA,
  type SidebarNavContribution
} from '@hermes/plugin-sdk'

import { ChalklinePage } from './chalkline-page'
import { CLASSROOM_LOCALES } from './classroom-locales'

const plugin: HermesPlugin = {
  id: 'chalkline',
  name: 'Chalkline',
  description: 'Connected teacher classroom for reviewed lessons, student work, learning questions and feedback.',
  register(ctx) {
    ctx.i18n.register(CLASSROOM_LOCALES)
    ctx.registerMany([
      {
        id: 'page',
        area: ROUTES_AREA,
        data: { path: '/chalkline' } satisfies RouteContribution,
        render: () => <ChalklinePage />
      },
      {
        id: 'nav',
        area: SIDEBAR_NAV_AREA,
        order: 1,
        data: { codicon: 'book', label: 'Chalkline', path: '/chalkline' } satisfies SidebarNavContribution
      },
      {
        id: 'open',
        area: PALETTE_AREA,
        data: {
          id: 'chalkline.open',
          label: 'Chalkline: Open teacher workspace',
          keywords: ['teacher', 'lesson', 'evidence', 'students'],
          run: () => host.navigate('/chalkline')
        } satisfies PaletteContribution
      }
    ])
  }
}

export default plugin
