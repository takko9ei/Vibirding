import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiClient } from '../api/client.ts'
import type { DraftObservation, ParseResult } from '../api/types.ts'
import { CapturePage } from './CapturePage.tsx'

const mediaId = '00000000-0000-0000-0000-000000000101'
const secondMediaId = '00000000-0000-0000-0000-000000000102'

const draft: DraftObservation = {
  client_draft_id: 'draft-1',
  place: '井之头公园',
  obs_date: '2026-09-07',
  time_of_day: '傍晚',
  count: 3,
  behavior: '贴水飞行',
  raw_note: '看到三只家燕',
  species_label: '家燕',
  species_id: '00000000-0000-0000-0000-000000000201',
  confidence: null,
  source: 'user',
  flags: [],
  photo_ids: [],
  needs_confirmation: false,
}

const parsed: ParseResult = {
  draft_observations: [draft],
  unmatched_photos: [],
  warnings: [],
  job_status: 'completed',
}

function photo(name = 'bird.jpg'): File {
  return new File([new Uint8Array([0xff, 0xd8, 0xff, 0xd9])], name, {
    type: 'image/jpeg',
  })
}

function makeClient(overrides: Partial<ApiClient> = {}): ApiClient {
  return {
    uploadMedia: vi.fn().mockResolvedValue({ media_id: mediaId, hash: 'abc', url: '/media/abc.jpg' }),
    parse: vi.fn().mockResolvedValue(parsed),
    createObservations: vi.fn().mockResolvedValue({
      session_id: '00000000-0000-0000-0000-000000000301',
      created: [],
      failed: [],
    }),
    listObservations: vi.fn(),
    getObservation: vi.fn(),
    updateObservation: vi.fn(),
    deleteObservation: vi.fn(),
    searchSpecies: vi.fn(),
    ...overrides,
  } as ApiClient
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

beforeEach(() => {
  vi.spyOn(URL, 'createObjectURL').mockImplementation((file) => `blob:${(file as File).name}`)
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('CapturePage', () => {
  it('parses text-only input without writing before confirmation', async () => {
    const user = userEvent.setup()
    const client = makeClient()
    render(<CapturePage client={client} />)

    await user.type(screen.getByLabelText('观察笔记'), '看到三只家燕')
    await user.click(screen.getByRole('button', { name: /整理观察笔记/ }))

    await waitFor(() =>
      expect((screen.getByLabelText('地点') as HTMLInputElement).value).toBe('井之头公园'),
    )
    expect(client.parse).toHaveBeenCalledWith({ text: '看到三只家燕', media_ids: [] })
    expect(client.createObservations).not.toHaveBeenCalled()
  })

  it('uploads and parses photo-only input', async () => {
    const user = userEvent.setup()
    const client = makeClient()
    render(<CapturePage client={client} />)

    await user.upload(screen.getByLabelText('选择照片'), photo())
    await screen.findByText('已上传')
    await user.click(screen.getByRole('button', { name: /整理观察笔记/ }))

    await waitFor(() => expect(client.parse).toHaveBeenCalledWith({ text: '', media_ids: [mediaId] }))
  })

  it('sends text and successful media IDs for mixed input', async () => {
    const user = userEvent.setup()
    const client = makeClient()
    render(<CapturePage client={client} />)

    await user.type(screen.getByLabelText('观察笔记'), '湖边一只鸬鹚')
    await user.upload(screen.getByLabelText('选择照片'), photo('cormorant.jpeg'))
    await screen.findByText('已上传')
    await user.click(screen.getByRole('button', { name: /整理观察笔记/ }))

    await waitFor(() =>
      expect(client.parse).toHaveBeenCalledWith({
        text: '湖边一只鸬鹚',
        media_ids: [mediaId],
      }),
    )
  })

  it('isolates an upload failure and allows an explicit retry', async () => {
    const user = userEvent.setup()
    const uploadMedia = vi
      .fn()
      .mockRejectedValueOnce(new Error('上传服务暂不可用'))
      .mockResolvedValueOnce({ media_id: mediaId, hash: 'abc', url: '/media/abc.jpg' })
    const client = makeClient({ uploadMedia })
    render(<CapturePage client={client} />)

    await user.upload(screen.getByLabelText('选择照片'), photo())
    await screen.findByText(/失败：上传服务暂不可用/)
    await user.click(screen.getByRole('button', { name: '重试' }))

    await screen.findByText('已上传')
    expect(uploadMedia).toHaveBeenCalledTimes(2)
  })

  it('preserves source input and retries a failed parse', async () => {
    const user = userEvent.setup()
    const parse = vi.fn().mockRejectedValueOnce(new Error('模型超时')).mockResolvedValueOnce(parsed)
    const client = makeClient({ parse })
    render(<CapturePage client={client} />)

    const note = screen.getByLabelText('观察笔记')
    await user.type(note, '看到三只家燕')
    await user.click(screen.getByRole('button', { name: /整理观察笔记/ }))
    await screen.findByText('模型超时')
    expect((note as HTMLTextAreaElement).value).toBe('看到三只家燕')

    await user.click(screen.getByRole('button', { name: /整理观察笔记/ }))
    await screen.findByRole('button', { name: '确认写入 1 条' })
    expect(parse).toHaveBeenCalledTimes(2)
  })

  it('edits a draft, reassigns a photo, confirms explicitly, and shows partial success', async () => {
    const user = userEvent.setup()
    const parseResult: ParseResult = {
      ...parsed,
      draft_observations: [
        { ...draft, photo_ids: [mediaId] },
        {
          ...draft,
          client_draft_id: 'draft-2',
          species_label: '鸬鹚',
          species_id: '00000000-0000-0000-0000-000000000202',
          raw_note: '又看到一只鸬鹚',
        },
      ],
    }
    const createObservations = vi.fn().mockResolvedValue({
      session_id: '00000000-0000-0000-0000-000000000301',
      created: [
        {
          client_draft_id: 'draft-1',
          observation_id: '00000000-0000-0000-0000-000000000401',
        },
      ],
      failed: [{ client_draft_id: 'draft-2', reason: '物种引用无效' }],
    })
    const client = makeClient({
      parse: vi.fn().mockResolvedValue(parseResult),
      createObservations,
    })
    render(<CapturePage client={client} />)

    await user.type(screen.getByLabelText('观察笔记'), '家燕和鸬鹚')
    await user.upload(screen.getByLabelText('选择照片'), photo())
    await screen.findByText('已上传')
    await user.click(screen.getByRole('button', { name: /整理观察笔记/ }))
    await screen.findByRole('button', { name: '确认写入 2 条' })

    const speciesInputs = screen.getAllByLabelText('物种')
    await user.clear(speciesInputs[0])
    await user.type(speciesInputs[0], '普通楼燕')
    await user.selectOptions(screen.getByLabelText('照片归属'), 'draft-2')
    expect(createObservations).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: '确认写入 2 条' }))

    await screen.findByText('部分记录已写入')
    expect(screen.getByText('物种引用无效')).toBeTruthy()
    expect(createObservations).toHaveBeenCalledWith(
      expect.objectContaining({
        confirmed: true,
        media_ids: [mediaId],
        observations: [
          expect.objectContaining({
            client_draft_id: 'draft-1',
            species_label: '普通楼燕',
            species_id: null,
            needs_confirmation: true,
            photo_ids: [],
          }),
          expect.objectContaining({ client_draft_id: 'draft-2', photo_ids: [mediaId] }),
        ],
      }),
    )
  })

  it('blocks duplicate parse and confirm requests while each request is pending', async () => {
    const user = userEvent.setup()
    const parsePending = deferred<ParseResult>()
    const confirmPending = deferred<{
      session_id: string
      created: never[]
      failed: never[]
    }>()
    const parse = vi.fn().mockReturnValue(parsePending.promise)
    const createObservations = vi.fn().mockReturnValue(confirmPending.promise)
    const client = makeClient({ parse, createObservations })
    render(<CapturePage client={client} />)

    await user.type(screen.getByLabelText('观察笔记'), '一只家燕')
    const parseButton = screen.getByRole('button', { name: /整理观察笔记/ })
    await user.click(parseButton)
    await user.click(parseButton)
    expect(parse).toHaveBeenCalledTimes(1)

    parsePending.resolve(parsed)
    const confirmButton = await screen.findByRole('button', { name: '确认写入 1 条' })
    await user.click(confirmButton)
    await user.click(confirmButton)
    expect(createObservations).toHaveBeenCalledTimes(1)

    confirmPending.resolve({
      session_id: secondMediaId,
      created: [],
      failed: [],
    })
    await screen.findByText('这批记录未能写入')
  })
})
