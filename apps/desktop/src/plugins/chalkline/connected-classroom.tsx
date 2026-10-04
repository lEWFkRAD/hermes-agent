import { Button, Input, usePluginI18n } from '@hermes/plugin-sdk'
import { useState } from 'react'

const CLASSROOM_ORIGIN = 'http://127.0.0.1:5195'

export function ConnectedClassroom() {
  const t = usePluginI18n('chalkline')
  const [access, setAccess] = useState('')
  const [source, setSource] = useState(CLASSROOM_ORIGIN)
  const [error, setError] = useState(false)

  function connect() {
    const code = access.trim().includes('#access=') ? access.trim().split('#access=')[1] : access.trim()

    if (!/^[A-Za-z0-9_-]{43}$/.test(code)) {
      setError(true)

      return
    }

    setSource(CLASSROOM_ORIGIN + '/#access=' + code)
    setAccess('')
    setError(false)
  }

  return (
    <section className="chalkline-classroom">
      <div className="chalkline-classroom__connect">
        <p>{t('connectionHint')}</p>
        <form
          onSubmit={event => {
            event.preventDefault()
            connect()
          }}
        >
          <Input
            aria-label={t('accessLabel')}
            autoComplete="off"
            onChange={event => setAccess(event.target.value)}
            placeholder={t('accessLabel')}
            type="password"
            value={access}
          />
          <Button type="submit">{t('connect')}</Button>
          <Button onClick={() => setSource(CLASSROOM_ORIGIN + '/?reload=' + Date.now())} type="button" variant="ghost">
            {t('reload')}
          </Button>
        </form>
        {error && <p role="alert">{t('invalidCode')}</p>}
      </div>
      <iframe
        className="chalkline-classroom__frame"
        key={source}
        referrerPolicy="no-referrer"
        sandbox="allow-scripts allow-same-origin allow-forms allow-downloads"
        src={source}
        title={t('frameTitle')}
      />
    </section>
  )
}
