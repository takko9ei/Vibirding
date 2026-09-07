const steps = ['输入', '智能整理', '确认']

export function CapturePage() {
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
              className={index === 0 ? 'steps__item steps__item--active' : 'steps__item'}
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

          <label className="field-label" htmlFor="observation-note">
            观察笔记
          </label>
          <textarea
            id="observation-note"
            placeholder="例如：傍晚在葛西临海公园，看到十几只家燕贴着水面飞……"
            rows={9}
          />

          <div className="photo-drop" aria-label="照片上传区域">
            <span className="photo-drop__icon" aria-hidden="true">
              +
            </span>
            <div>
              <strong>把照片放在这里</strong>
              <p>JPEG · 单张不超过 2 MB</p>
            </div>
          </div>

          <button className="button button--primary" disabled type="button">
            整理观察笔记
            <span aria-hidden="true">→</span>
          </button>
        </section>

        <section className="panel preview-panel" aria-labelledby="preview-title">
          <div className="panel__heading">
            <div>
              <p className="eyebrow">PREVIEW</p>
              <h2 id="preview-title">确认观察记录</h2>
            </div>
            <span className="count-badge">0 条草稿</span>
          </div>

          <div className="empty-state">
            <span className="empty-state__mark" aria-hidden="true">
              ✦
            </span>
            <h3>整理结果会出现在这里</h3>
            <p>写下地点、鸟种、数量或行为，也可以只放照片。</p>
            <div className="empty-state__tags" aria-hidden="true">
              <span>文字拆分</span>
              <span>照片匹配</span>
              <span>确认后写入</span>
            </div>
          </div>
        </section>
      </div>
    </section>
  )
}
