import type { DraftObservation } from '../api/types.ts'
import type { LocalPhoto } from './PhotoGrid.tsx'

interface DraftCardProps {
  draft: DraftObservation
  index: number
  photos: LocalPhoto[]
  disabled: boolean
  onChange: (draft: DraftObservation) => void
}

const sourceLabels: Record<string, string> = {
  user: '来自文字',
  bird_id: '照片生成',
  inferred: '描述推断',
  manual: '手动记录',
}

function nullable(value: string): string | null {
  const clean = value.trim()
  return clean || null
}

export function DraftCard({ draft, index, photos, disabled, onChange }: DraftCardProps) {
  const assignedPhotos = photos.filter(
    (photo) => photo.upload && draft.photo_ids.includes(photo.upload.media_id),
  )

  return (
    <article className="draft-card">
      <header className="draft-card__header">
        <span className="draft-card__number">{String(index + 1).padStart(2, '0')}</span>
        <div>
          <p className="eyebrow">OBSERVATION</p>
          <h3>{draft.species_label || '待确认物种'}</h3>
        </div>
        <span className="source-badge">{sourceLabels[draft.source] ?? draft.source}</span>
      </header>

      {(draft.needs_confirmation || draft.flags.length > 0) && (
        <div className="warning-box" role="status">
          {draft.needs_confirmation && <strong>这条记录需要你确认</strong>}
          {draft.flags.length > 0 && <span>标记：{draft.flags.join('、')}</span>}
        </div>
      )}

      <div className="draft-meta" aria-label="草稿只读信息">
        <span>
          置信度：{draft.confidence === null ? '未提供' : `${Math.round(draft.confidence * 100)}%`}
        </span>
        <span title={draft.client_draft_id}>草稿编号：{draft.client_draft_id}</span>
      </div>

      <div className="draft-fields">
        <label className="draft-fields__wide">
          <span>物种</span>
          <input
            disabled={disabled}
            onChange={(event) =>
              onChange({
                ...draft,
                species_label: nullable(event.target.value),
                species_id: null,
                needs_confirmation: true,
              })
            }
            value={draft.species_label ?? ''}
          />
        </label>
        <label>
          <span>数量</span>
          <input
            disabled={disabled}
            min="1"
            onChange={(event) =>
              onChange({
                ...draft,
                count: event.target.value === '' ? null : Number(event.target.value),
              })
            }
            type="number"
            value={draft.count ?? ''}
          />
        </label>
        <label className="draft-fields__wide">
          <span>地点</span>
          <input
            disabled={disabled}
            onChange={(event) => onChange({ ...draft, place: nullable(event.target.value) })}
            value={draft.place ?? ''}
          />
        </label>
        <label>
          <span>日期</span>
          <input
            disabled={disabled}
            onChange={(event) => onChange({ ...draft, obs_date: nullable(event.target.value) })}
            type="date"
            value={draft.obs_date ?? ''}
          />
        </label>
        <label>
          <span>时段</span>
          <input
            disabled={disabled}
            onChange={(event) => onChange({ ...draft, time_of_day: nullable(event.target.value) })}
            placeholder="如：傍晚"
            value={draft.time_of_day ?? ''}
          />
        </label>
        <label className="draft-fields__wide">
          <span>行为</span>
          <input
            disabled={disabled}
            onChange={(event) => onChange({ ...draft, behavior: nullable(event.target.value) })}
            value={draft.behavior ?? ''}
          />
        </label>
        <label className="draft-fields__full">
          <span>对应原文</span>
          <textarea
            disabled={disabled}
            onChange={(event) => onChange({ ...draft, raw_note: event.target.value })}
            rows={3}
            value={draft.raw_note}
          />
        </label>
      </div>

      <div className="draft-photos">
        <strong>关联照片 · {assignedPhotos.length}</strong>
        {assignedPhotos.length > 0 ? (
          <div className="draft-photos__list">
            {assignedPhotos.map((photo) => (
              <img alt={photo.file.name} key={photo.localId} src={photo.previewUrl} />
            ))}
          </div>
        ) : (
          <span>暂无照片，可在左侧照片卡片中调整归属。</span>
        )}
      </div>
    </article>
  )
}
