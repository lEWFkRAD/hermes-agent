/** Keep a product fork's OS links separate from the regular Hermes client. */
export function desktopProductProtocol(appId: string, development: boolean) {
  const base = appId.startsWith('com.onyxintelligence.chalkline') ? 'chalkline' : 'hermes'
  const protocol = development ? `${base}-dev` : base

  return { protocol, accepted: development ? [protocol, base] : [base] }
}
