import { useEffect, useMemo, useRef, useState } from 'react'
import { apiClient, type ApiClient } from '../api/client.ts'
import type { BatchWriteResult, DraftObservation, ParseResult } from '../api/types.ts'
import { DraftCard } from '../components/DraftCard.tsx'
import { NoteEditor } from '../components/NoteEditor.tsx'
import { PhotoGrid, type LocalPhoto } from '../components/PhotoGrid.tsx'
import { WriteResultPanel } from '../components/WriteResultPanel.tsx'

const steps = ['输入', '智能整理', '确认']
const maxPhotoBytes = 2 * 1024 * 1024

type WorkflowPhase = 'input' | 'parsing' | 'preview' | 'confirming' | 'result'

interface CapturePageProps {
  client?: ApiClient
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message
  return '发生未知错误，请稍后重试。'
}

function validatePhoto(file: File): string | null {
  const extensionOkay = /\.(jpe?g)$/i.test(file.name)
  const mimeOkay = file.type === 'image/jpeg' || file.type === 'image/jpg'
  if (!extensionOkay || !mimeOkay) return '只接受 JPEG（.jpg / .jpeg）'
  if (file.size === 0) return '照片内容为空'
  if (file.size > maxPhotoBytes) return '超过 2 MiB 上限'
  return null
}

function localId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`
}

function uniqueSuccessfulMedia(photos: LocalPhoto[]): string[] {
  return [
    ...new Set(
      photos.flatMap((photo) =>
        photo.status === 'success' && photo.upload ? [photo.upload.media_id] : [],
      ),
    ),
  ]
}

export function CapturePage({ client = apiClient }: CapturePageProps) {
  const [text, setText] = useState('')
  const [photos, setPhotos] = useState<LocalPhoto[]>([])
  const [phase, setPhase] = useState<WorkflowPhase>('input')
  const [drafts, setDrafts] = useState<DraftObservation[]>([])
  const [warnings, setWarnings] = useState<string[]>([])
  const [parseError, setParseError] = useState<string | null>(null)
  const [confirmError, setConfirmError] = useState<string | null>(null)
  const [previewIsStale, setPreviewIsStale] = useState(false)
  const [result, setResult] = useState<BatchWriteResult | null>(null)
  const photosRef = useRef(photos)

  useEffect(() => {
    photosRef.current = photos
  }, [photos])

  useEffect(
    () => () => {
      photosRef.current.forEach((photo) => URL.revokeObjectURL(photo.previewUrl))
    },
    [],
  )

  const mediaIds = useMemo(() => uniqueSuccessfulMedia(photos), [photos])
  const uploadsPending = photos.some((photo) => photo.status === 'uploading')
  const workflowPending = phase === 'parsing' || phase === 'confirming'
  const inputLocked = workflowPending || phase === 'result'
  const hasInput = text.trim().length > 0 || mediaIds.length > 0
  const canParse = hasInput && !uploadsPending && !workflowPending && phase !== 'result'
  const assignedMedia = new Set(drafts.flatMap((draft) => draft.photo_ids))
  const unassignedCount = mediaIds.filter((mediaId) => !assignedMedia.has(mediaId)).length
  const activeStep = phase === 'input' ? 0 : phase === 'parsing' ? 1 : 2

  function markSourceChanged() {
    if (phase === 'preview' || phase === 'confirming') setPreviewIsStale(true)
    setParseError(null)
  }

  async function uploadPhoto(photo: LocalPhoto) {
    try {
      const upload = await client.uploadMedia(photo.file)
      setPhotos((current) =>
        current.map((item) =>
          item.localId === photo.localId
            ? { ...item, status: 'success', upload, error: null, canRetry: false }
            : item,
        ),
      )
    } catch (error) {
      setPhotos((current) =>
        current.map((item) =>
          item.localId === photo.localId
            ? {
                ...item,
                status: 'error',
                upload: null,
                error: errorMessage(error),
                canRetry: true,
              }
            : item,
        ),
      )
    }
  }

  function addFiles(files: File[]) {
    if (!files.length) return
    markSourceChanged()
    const newPhotos = files.map<LocalPhoto>((file) => {
      const validationError = validatePhoto(file)
      return {
        localId: localId(),
        file,
        previewUrl: URL.createObjectURL(file),
        status: validationError ? 'error' : 'uploading',
        upload: null,
        error: validationError,
        canRetry: false,
      }
    })
    setPhotos((current) => [...current, ...newPhotos])
    newPhotos
      .filter((photo) => photo.status === 'uploading')
      .forEach((photo) => void uploadPhoto(photo))
  }

  function removePhoto(photoId: string) {
    const target = photos.find((photo) => photo.localId === photoId)
    if (!target) return
    markSourceChanged()
    URL.revokeObjectURL(target.previewUrl)
    setPhotos((current) => current.filter((photo) => photo.localId !== photoId))
    if (target.upload) {
      setDrafts((current) =>
        current.map((draft) => ({
          ...draft,
          photo_ids: draft.photo_ids.filter((mediaId) => mediaId !== target.upload!.media_id),
        })),
      )
    }
  }

  function retryPhoto(photoId: string) {
    const target = photos.find((photo) => photo.localId === photoId)
    if (!target) return
    setPhotos((current) =>
      current.map((photo) =>
        photo.localId === photoId
          ? { ...photo, status: 'uploading', error: null, canRetry: false }
          : photo,
      ),
    )
    void uploadPhoto(target)
  }

  async function parseInput() {
    if (!canParse) return
    setPhase('parsing')
    setParseError(null)
    setConfirmError(null)
    try {
      const parsed: ParseResult = await client.parse({ text, media_ids: mediaIds })
      setDrafts(parsed.draft_observations)
      setWarnings(parsed.warnings)
      setPreviewIsStale(false)
      setPhase('preview')
    } catch (error) {
      setParseError(errorMessage(error))
      setPhase(drafts.length > 0 ? 'preview' : 'input')
    }
  }

  function updateDraft(nextDraft: DraftObservation) {
    setDrafts((current) =>
      current.map((draft) =>
        draft.client_draft_id === nextDraft.client_draft_id ? nextDraft : draft,
      ),
    )
    setConfirmError(null)
  }

  function assignPhoto(mediaId: string, clientDraftId: string | null) {
    setDrafts((current) =>
      current.map((draft) => {
        const withoutPhoto = draft.photo_ids.filter((photoId) => photoId !== mediaId)
        return draft.client_draft_id === clientDraftId
          ? { ...draft, photo_ids: [...withoutPhoto, mediaId] }
          : { ...draft, photo_ids: withoutPhoto }
      }),
    )
    setConfirmError(null)
  }

  async function confirmWrite() {
    if (phase !== 'preview' || previewIsStale || drafts.length === 0) return
    setPhase('confirming')
    setConfirmError(null)
    try {
      const writeResult = await client.createObservations({
        text,
        media_ids: mediaIds,
        observations: drafts,
        confirmed: true,
      })
      setResult(writeResult)
      setPhase('result')
    } catch (error) {
      setConfirmError(
        `${errorMessage(error)} 写入请求不会自动重试，以免产生重复记录；请确认后再手动尝试。`,
      )
      setPhase('preview')
    }
  }

  function resetWorkspace() {
    photos.forEach((photo) => URL.revokeObjectURL(photo.previewUrl))
    setText('')
    setPhotos([])
    setDrafts([])
    setWarnings([])
    setParseError(null)
    setConfirmError(null)
    setPreviewIsStale(false)
    setResult(null)
    setPhase('input')
  }

  return (
    <section className="workspace" aria-labelledby="capture-title">
      <div className="page-heading">
        <div>
          <p className="eyebrow">FIELD NOTE / 01</p>
          <h1 id="capture-title">记下刚才看到的鸟</h1>
        </div>
        <ol className="steps" aria-label="记录步骤">
          {steps.map((step, index) => (
            <li
              aria-current={index === activeStep ? 'step' : undefined}
              className={index === activeStep ? 'steps__item steps__item--active' : 'steps__item'}
              key={step}
            >
              <span>{index + 1}</span>
              {step}
            </li>
          ))}
        </ol>
      </div>

      <div className="capture-grid">
        <section className="panel panel--yellow note-panel" aria-labelledby="note-title">
          <div className="panel__heading">
            <div>
              <p className="eyebrow">RAW NOTE</p>
              <h2 id="note-title">今天看到了什么？</h2>
            </div>
            <span className="number-stamp">01</span>
          </div>

          <NoteEditor
            disabled={inputLocked}
            onChange={(value) => {
              setText(value)
              markSourceChanged()
            }}
            value={text}
          />
          <PhotoGrid
            disabled={inputLocked}
            drafts={phase === 'preview' || phase === 'confirming' ? drafts : []}
            onAssignment={assignPhoto}
            onFiles={addFiles}
            onRemove={removePhoto}
            onRetry={retryPhoto}
            photos={photos}
          />

          {parseError && (
            <div className="error-box" role="alert">
              <strong>整理失败</strong>
              <span>{parseError}</span>
            </div>
          )}
          {previewIsStale && (
            <div className="warning-box" role="status">
              <strong>输入已改变</strong>
              <span>请重新整理后再确认写入，照片无需重新上传。</span>
            </div>
          )}

          {phase !== 'result' && (
            <button className="button button--primary" disabled={!canParse} onClick={parseInput} type="button">
              {phase === 'parsing'
                ? '正在智能整理…'
                : drafts.length > 0
                  ? '重新整理观察笔记'
                  : '整理观察笔记'}
              {phase !== 'parsing' && <span aria-hidden="true">→</span>}
            </button>
          )}
        </section>

        <section className="panel preview-panel" aria-labelledby="preview-title">
          <div className="panel__heading">
            <div>
              <p className="eyebrow">PREVIEW</p>
              <h2 id="preview-title">确认观察记录</h2>
            </div>
            <span className="count-badge">{drafts.length} 条草稿</span>
          </div>

          {phase === 'result' && result ? (
            <WriteResultPanel drafts={drafts} onReset={resetWorkspace} result={result} />
          ) : drafts.length > 0 ? (
            <div className="preview-content">
              {warnings.length > 0 && (
                <div className="warning-list" role="status">
                  <strong>整理提示</strong>
                  <ul>
                    {warnings.map((warning, index) => (
                      <li key={`${index}-${warning}`}>{warning}</li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="draft-list">
                {drafts.map((draft, index) => (
                  <DraftCard
                    disabled={workflowPending}
                    draft={draft}
                    index={index}
                    key={draft.client_draft_id}
                    onChange={updateDraft}
                    photos={photos}
                  />
                ))}
              </div>

              {confirmError && (
                <div className="error-box" role="alert">
                  <strong>写入失败</strong>
                  <span>{confirmError}</span>
                </div>
              )}

              <div className="confirm-bar">
                <div>
                  <strong>即将写入 {drafts.length} 条记录</strong>
                  <span>
                    {assignedMedia.size} 张照片已归属
                    {unassignedCount > 0 ? `，${unassignedCount} 张仅保留在本批次` : ''}
                  </span>
                </div>
                <div className="confirm-bar__actions">
                  <button
                    className="button button--secondary"
                    disabled={workflowPending}
                    onClick={() => document.getElementById('observation-note')?.focus()}
                    type="button"
                  >
                    继续修改
                  </button>
                  <button
                    className="button button--primary"
                    disabled={workflowPending || previewIsStale || drafts.length === 0}
                    onClick={confirmWrite}
                    type="button"
                  >
                    {phase === 'confirming' ? '正在写入…' : `确认写入 ${drafts.length} 条`}
                  </button>
                </div>
              </div>
            </div>
          ) : phase === 'parsing' ? (
            <div className="empty-state empty-state--busy" aria-live="polite">
              <span className="empty-state__mark" aria-hidden="true">✦</span>
              <h3>正在拆分笔记与匹配照片</h3>
              <p>图片较多时可能需要几十秒，请保持这个页面打开。</p>
            </div>
          ) : (
            <div className="empty-state">
              <span className="empty-state__mark" aria-hidden="true">✦</span>
              <h3>整理结果会出现在这里</h3>
              <p>写下地点、鸟种、数量或行为，也可以只放照片。</p>
              <div className="empty-state__tags" aria-hidden="true">
                <span>文字拆分</span>
                <span>照片匹配</span>
                <span>确认后写入</span>
              </div>
            </div>
          )}
        </section>
      </div>
    </section>
  )
}
