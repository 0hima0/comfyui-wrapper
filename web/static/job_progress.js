/** Render progress once, inside the floating execution controls. */
class JobProgressView {
  constructor(root) {
    this.listeners = new Set();
    this.root = root;
    this.header = root.querySelector('#progress-state');
    this.spinner = root.querySelector('#progress-spinner');
    this.bar = root.querySelector('#progress-bar');
    this.label = root.querySelector('#progress-label');
    this.elapsed = root.querySelector('#progress-elapsed');
    this.steps = [];
    this.timer = null;
    this.data = null;
    this.suppressed = false;
    const list = root.querySelector('#progress-stages');
    for (const title of ['受付','画像解析','Prompt作成','画像生成','保存']) {
      const item = document.createElement('li'); item.textContent = title;
      list.append(item); this.steps.push({item,title});
    }
  }

  subscribe(listener) { this.listeners.add(listener); return () => this.listeners.delete(listener); }

  setSuppressed(value) {
    this.suppressed = value;
    this.root.hidden = value || !this.data;
  }

  updateElapsed() {
    const started = Date.parse(this.data?.created_at || '');
    const finished = Date.parse(this.data?.finished_at || '') || Date.now();
    if (!Number.isFinite(started)) { this.elapsed.textContent = ''; return; }
    const seconds = Math.max(0, Math.floor((finished-started)/1000));
    this.elapsed.textContent = `経過 ${Math.floor(seconds/60)}分${String(seconds%60).padStart(2,'0')}秒`;
  }

  render(data) {
    this.data = data;
    this.root.hidden = this.suppressed;
    const phase = data.progress || {};
    const running = data.state === 'running', done = data.state === 'done', failed = data.state === 'error' || data.state === 'cancelled';
    const index = done ? 5 : ({upload:0,analysis:1,compose:2,queue:3,generate:3,save:4}[phase.stage] ?? -1);
    const execute = data.settings?.execute !== false;
    const titles = {upload:'受付',analysis:'画像解析',compose:'Prompt作成',queue:'キュー待ち',generate:'画像生成',save:'保存'};
    this.root.dataset.state = data.state;
    this.spinner.hidden = !running;
    this.header.textContent = done ? '完了' : data.state === 'cancelled' ? '停止済み' : data.cancel_requested ? '停止処理中…' : failed ? '失敗・中断' : running ? '実行中 · '+(titles[phase.stage] || '処理中') : '接続確認';
    for (const [position,step] of this.steps.entries()) {
      const skipped = position === 3 && !execute;
      step.item.dataset.state = skipped ? 'skipped' : position < index ? 'complete' : position === index ? (failed ? 'failed' : 'current') : 'pending';
      step.item.textContent = step.title + (skipped ? '（スキップ）' : '');
      if (position === index) step.item.setAttribute('aria-current','step');
      else step.item.removeAttribute('aria-current');
    }
    const current = phase.current, total = phase.total;
    const measured = running && phase.stage === 'generate' && typeof current === 'number' && typeof total === 'number'
      && Number.isFinite(current) && Number.isFinite(total) && total > 0 && current >= 0 && current <= total;
    this.bar.hidden = failed || data.state === 'disconnected';
    if (measured) {
      this.bar.max = total; this.bar.value = current;
      this.label.textContent = `生成ステップ ${current} / ${total}（${Math.floor(current/total*100)}%）`;
    } else if (done) {
      this.bar.max = 1; this.bar.value = 1; this.label.textContent = data.message || '完了しました。';
    } else {
      this.bar.removeAttribute('value');
      this.label.textContent = data.state === 'error' ? 'エラー内容を確認して再実行してください。' :
        failed || data.state === 'disconnected' ? data.message : phase.detail || data.message || '処理中…';
    }
    this.bar.setAttribute('aria-label', measured ? '画像生成ステップの進捗' : '処理の進行状況');
    this.updateElapsed();
    if (running && this.timer === null) this.timer = setInterval(()=>this.updateElapsed(),1000);
    if (!running && this.timer !== null) { clearInterval(this.timer); this.timer = null; }
    for (const listener of this.listeners) listener(data);
  }

  disconnected(message) {
    if (this.data) this.render({...this.data, state:'disconnected', message:message+' 再読込で進捗を確認できます。'});
  }
}
