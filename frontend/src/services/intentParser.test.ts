import { describe, expect, it } from 'vitest'
import { parseIntent } from './intentParser'

const lg = { volumeTarget: 'lg' as const }

describe('parseIntent', () => {
  it('parses a channel', () => {
    const r = parseIntent('ערוץ 12', lg)
    expect(r.steps).toHaveLength(1)
    expect(r.steps[0].command).toEqual({ target: 'hot', action: 'digits', params: { digits: '12' } })
  })
  it('routes volume to the configured target', () => {
    expect(parseIntent('תגביר', lg).steps[0].command.target).toBe('lg')
    expect(parseIntent('תגביר', { volumeTarget: 'hot' }).steps[0].command.target).toBe('hot')
  })
  it('splits sequences', () => {
    const r = parseIntent('שים ערוץ 12 ואז תנמיך', lg)
    expect(r.steps.map((s) => s.command.action)).toEqual(['digits', 'volume_down'])
    expect(r.unrecognized).toEqual([])
  })
  it('parses HDMI input and youtube', () => {
    expect(parseIntent('תעבור ל-HDMI 2', lg).steps[0].command.params).toEqual({ input: 'HDMI_2' })
    expect(parseIntent('פתח יוטיוב', lg).steps[0].command.params).toEqual({ app: 'youtube' })
  })
  it('opens streaming apps on the TV by default and on the box when asked', () => {
    expect(parseIntent('פתח נטפליקס', lg).steps[0].command).toEqual({ target: 'lg', action: 'launch_app', params: { app: 'netflix' } })
    expect(parseIntent('פתח ספוטיפיי בממיר', lg).steps[0].command).toEqual({ target: 'hot', action: 'launch_app', params: { app: 'spotify' } })
  })
  it('accepts the Hebrew conjunction prefix', () => {
    const r = parseIntent('ערוץ 12, ותנמיך, וכבה את הטלוויזיה', lg)
    expect(r.steps.map((s) => s.command.action)).toEqual(['digits', 'volume_down', 'power_off'])
  })
  it('reports unrecognized text instead of guessing', () => {
    const r = parseIntent('מצא לי סרט מצחיק', lg)
    expect(r.steps).toHaveLength(0)
    expect(r.unrecognized).toEqual(['מצא לי סרט מצחיק'])
  })
  it('does not partially drop a mixed sentence', () => {
    const r = parseIntent('השתק ואז ספר לי בדיחה', lg)
    expect(r.steps).toHaveLength(1)
    expect(r.unrecognized).toEqual(['ספר לי בדיחה'])
  })
})
