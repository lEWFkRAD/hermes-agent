import { fireEvent, render, screen } from '@testing-library/react'
import type { ComponentProps } from 'react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@hermes/plugin-sdk', () => ({
  usePluginI18n: () => (key: string) => key,
  Button: (props: ComponentProps<'button'>) => <button {...props} />,
  Input: (props: ComponentProps<'input'>) => <input {...props} />
}))

import { ConnectedClassroom } from './connected-classroom'

describe('connected classroom access', () => {
  it('keeps access on the local classroom and rejects malformed credentials', () => {
    render(<ConnectedClassroom />)
    const input = screen.getByLabelText('accessLabel')
    fireEvent.change(input, { target: { value: 'https://unrelated.example' } })
    fireEvent.click(screen.getByText('connect'))
    expect(screen.getByRole('alert').textContent).toBe('invalidCode')
    expect(screen.getByTitle('frameTitle').getAttribute('src')).toBe('http://127.0.0.1:5195')

    const token = 'a'.repeat(43)
    fireEvent.change(input, { target: { value: 'https://unrelated.example/#access=' + token } })
    fireEvent.click(screen.getByText('connect'))
    const frame = screen.getByTitle('frameTitle')
    expect(frame.getAttribute('src')).toBe('http://127.0.0.1:5195/#access=' + token)
    expect(frame.getAttribute('sandbox')).not.toContain('allow-popups')
    expect(frame.getAttribute('sandbox')).not.toContain('allow-top-navigation')
  })
})
