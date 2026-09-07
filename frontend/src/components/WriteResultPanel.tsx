import type { BatchWriteResult, DraftObservation } from '../api/types.ts'

interface WriteResultPanelProps {
  result: BatchWriteResult
  drafts: DraftObservation[]
  onReset: () => void
}

export function WriteResultPanel({ result, drafts, onReset }: WriteResultPanelProps) {
  const labelFor = (clientDraftId: string) =>
    drafts.find((draft) => draft.client_draft_id === clientDraftId)?.species_label ?? '待确认物种'
  const state = result.created.length === 0 ? 'failed' : result.failed.length > 0 ? 'partial' : 'completed'
  const title = {
    completed: '全部写入完成',
    partial: '部分记录已写入',
    failed: '这批记录未能写入',
  }[state]

  return (
    <div className={`write-result write-result--${state}`} aria-live="polite">
      <span className="write-result__mark" aria-hidden="true">
        {state === 'completed' ? '✓' : state === 'partial' ? '!' : '×'}
      </span>
      <div>
        <p className="eyebrow">WRITE RESULT</p>
        <h3>{title}</h3>
        <p>
          成功 {result.created.length} 条，失败 {result.failed.length} 条。批次编号：
          <code>{result.session_id}</code>
        </p>
      </div>

      {result.created.length > 0 && (
        <section>
          <h4>已写入</h4>
          <ul>
            {result.created.map((item) => (
              <li key={item.client_draft_id}>
                <strong>{labelFor(item.client_draft_id)}</strong>
                <span>记录编号 {item.observation_id}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {result.failed.length > 0 && (
        <section>
          <h4>未写入</h4>
          <ul>
            {result.failed.map((item) => (
              <li key={item.client_draft_id}>
                <strong>{labelFor(item.client_draft_id)}</strong>
                <span>{item.reason}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <button className="button button--primary" onClick={onReset} type="button">
        记录下一次观察
      </button>
    </div>
  )
}
