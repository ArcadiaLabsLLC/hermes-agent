import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { I18nProvider, TRANSLATIONS, useI18n } from '@/i18n'
import type { I18nContextValue } from '@/i18n'

import { UninstallSection } from './uninstall-section'

let i18n: I18nContextValue

function Surface() {
  i18n = useI18n()

  return <UninstallSection />
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})
it.each(['gui', 'lite', 'full'] as const)(
  'localizes confirmation for %s without changing mode or running before confirmation',
  async mode => {
    const run = vi.fn().mockResolvedValue({ ok: false })
    vi.stubGlobal('hermesDesktop', {
      uninstall: { summary: async () => ({ agent_installed: true, running_app_path: '/fixture/Hermes.app' }), run }
    })
    render(
      <I18nProvider configClient={null} initialLocale="zh">
        <Surface />
      </I18nProvider>
    )
    const zh = TRANSLATIONS.zh.settings.uninstallSection
    await screen.findByText(zh.uninstallHermes)
    fireEvent.click(screen.getByRole('button', { name: new RegExp(zh.options[mode].title) }))
    expect(screen.getByText(zh.confirmBody(zh.options[mode].consequence))).toBeTruthy()
    expect(run).not.toHaveBeenCalled()
    await act(() => i18n.setLocale('ja'))
    const ja = TRANSLATIONS.ja.settings.uninstallSection
    expect(screen.getByText(ja.confirmBody(ja.options[mode].consequence))).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: ja.yesUninstall }))
    expect(run).toHaveBeenCalledWith(mode)
  }
)

// Fork (row 87, mission-control-queue.md): the confirm step warns that removing the agent
// also deletes the code checkout's git history, which this tool does not back up.

function stubBridge(summary: { agent_installed: boolean }) {
  const run = vi.fn().mockResolvedValue({ ok: true })

  vi.stubGlobal('hermesDesktop', {
    uninstall: {
      summary: vi.fn().mockResolvedValue(summary),
      run
    }
  })

  return { run }
}

describe('UninstallSection', () => {
  it('warns about lost git history when confirming an agent-removing mode', async () => {
    stubBridge({ agent_installed: true })

    render(<UninstallSection />)

    const liteButton = await screen.findByText('Uninstall GUI + agent, keep my data')
    fireEvent.click(liteButton)

    expect(await screen.findByText('Confirm uninstall')).toBeTruthy()
    expect(screen.getByText(/git history/i)).toBeTruthy()
  })

  it('does not warn about git history for the GUI-only mode', async () => {
    stubBridge({ agent_installed: true })

    render(<UninstallSection />)

    const guiButton = await screen.findByText('Uninstall Chat GUI only')
    fireEvent.click(guiButton)

    expect(await screen.findByText('Confirm uninstall')).toBeTruthy()
    expect(screen.queryByText(/git history/i)).toBeNull()
  })
})
