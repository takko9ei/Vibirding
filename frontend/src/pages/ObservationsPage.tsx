import { Link } from 'react-router-dom'

export function ObservationsPage() {
  return (
    <section className="workspace" aria-labelledby="observations-title">
      <div className="page-heading page-heading--records">
        <div>
          <p className="eyebrow">FIELD ARCHIVE / 02</p>
          <h1 id="observations-title">观察记录</h1>
        </div>
        <Link className="button button--compact" to="/">
          ＋ 记一笔
        </Link>
      </div>

      <form
        className="filters"
        aria-label="筛选观察记录"
        onSubmit={(event) => event.preventDefault()}
      >
        <label>
          <span>鸟种</span>
          <input name="species" placeholder="输入鸟种" type="search" />
        </label>
        <label>
          <span>地点</span>
          <input name="place" placeholder="输入地点" type="search" />
        </label>
        <label>
          <span>开始日期</span>
          <input name="date_from" type="date" />
        </label>
        <label>
          <span>结束日期</span>
          <input name="date_to" type="date" />
        </label>
        <button className="button button--filter" disabled type="submit">
          筛选
        </button>
      </form>

      <div className="records-grid">
        <section className="panel records-panel" aria-labelledby="list-title">
          <div className="panel__heading">
            <div>
              <p className="eyebrow">RECENT SIGHTINGS</p>
              <h2 id="list-title">最近记录</h2>
            </div>
            <span className="count-badge count-badge--purple">0 条</span>
          </div>
          <div className="list-placeholder">
            <span aria-hidden="true">◎</span>
            <div>
              <h3>记录列表等待加载</h3>
              <p>之后可以在这里按鸟种、地点和日期筛选。</p>
            </div>
          </div>
        </section>

        <aside className="panel panel--mint detail-panel" aria-labelledby="detail-title">
          <div className="panel__heading">
            <div>
              <p className="eyebrow">DETAIL</p>
              <h2 id="detail-title">记录详情</h2>
            </div>
            <span className="number-stamp number-stamp--small">—</span>
          </div>
          <div className="detail-placeholder">
            <span className="empty-state__mark empty-state__mark--small" aria-hidden="true">
              ↗
            </span>
            <h3>选择一条观察记录</h3>
            <p>照片、地点、数量和原始笔记会在这里展开。</p>
          </div>
        </aside>
      </div>
    </section>
  )
}
