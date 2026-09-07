import { useRef } from 'react'
import type { DraftObservation, MediaUploadResponse } from '../api/types.ts'

export interface LocalPhoto {
  localId: string
  file: File
  previewUrl: string
  status: 'uploading' | 'success' | 'error'
  upload: MediaUploadResponse | null
  error: string | null
  canRetry: boolean
}

interface PhotoGridProps {
  photos: LocalPhoto[]
  drafts: DraftObservation[]
  disabled: boolean
  onFiles: (files: File[]) => void
  onRemove: (localId: string) => void
  onRetry: (localId: string) => void
  onAssignment: (mediaId: string, clientDraftId: string | null) => void
}

function assignmentFor(photo: LocalPhoto, drafts: DraftObservation[]): string {
  const mediaId = photo.upload?.media_id
  if (!mediaId) return ''
  return drafts.find((draft) => draft.photo_ids.includes(mediaId))?.client_draft_id ?? ''
}

export function PhotoGrid({
  photos,
  drafts,
  disabled,
  onFiles,
  onRemove,
  onRetry,
  onAssignment,
}: PhotoGridProps) {
  const inputRef = useRef<HTMLInputElement>(null)

  return (
    <div className="photo-field">
      <input
        accept="image/jpeg,.jpg,.jpeg"
        aria-label="选择照片"
        className="visually-hidden"
        disabled={disabled}
        id="photo-input"
        multiple
        onChange={(event) => {
          onFiles(Array.from(event.target.files ?? []))
          event.target.value = ''
        }}
        ref={inputRef}
        type="file"
      />
      <button
        className="photo-drop"
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
        type="button"
      >
        <span className="photo-drop__icon" aria-hidden="true">
          +
        </span>
        <span>
          <strong>插入照片</strong>
          <small>可多选 · JPEG · 单张不超过 2 MB</small>
        </span>
      </button>

      {photos.length > 0 && (
        <ul className="photo-grid" aria-label="待提交照片">
          {photos.map((photo) => (
            <li className={`photo-tile photo-tile--${photo.status}`} key={photo.localId}>
              <img alt={photo.file.name} src={photo.previewUrl} />
              <div className="photo-tile__body">
                <strong title={photo.file.name}>{photo.file.name}</strong>
                <span className="status-label" aria-live="polite">
                  {photo.status === 'uploading' && '上传中…'}
                  {photo.status === 'success' && '已上传'}
                  {photo.status === 'error' && `失败：${photo.error}`}
                </span>
                {photo.status === 'success' && drafts.length > 0 && photo.upload && (
                  <label>
                    <span>照片归属</span>
                    <select
                      disabled={disabled}
                      onChange={(event) =>
                        onAssignment(photo.upload!.media_id, event.target.value || null)
                      }
                      value={assignmentFor(photo, drafts)}
                    >
                      <option value="">不写入任何草稿</option>
                      {drafts.map((draft, index) => (
                        <option key={draft.client_draft_id} value={draft.client_draft_id}>
                          {index + 1}. {draft.species_label || '待确认物种'}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                <div className="photo-tile__actions">
                  {photo.status === 'error' && photo.canRetry && (
                    <button disabled={disabled} onClick={() => onRetry(photo.localId)} type="button">
                      重试
                    </button>
                  )}
                  <button disabled={disabled} onClick={() => onRemove(photo.localId)} type="button">
                    移除
                  </button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
