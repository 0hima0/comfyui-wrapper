/** Render execution controls from explicit generation/progress state. */
class ExecutionControls {
 constructor({gate,progress,bar,elements,hasImages,document:doc=document,window:win=window,ResizeObserver:Observer=globalThis.ResizeObserver}){
  Object.assign(this,{gate,progress,bar,elements,hasImages,doc,win});
  this.unsubscribeGate=gate.subscribe(()=>this.render());
  this.unsubscribeProgress=progress.subscribe(()=>this.render());
  this.measure=()=>{
   if(!this.bar)return;
   const rect=this.bar.getBoundingClientRect();
   this.doc.documentElement.style.setProperty('--runbar-offset',(rect.height?Math.ceil(rect.bottom+16):28)+'px');
  };
  if(bar&&Observer){this.observer=new Observer(this.measure);this.observer.observe(bar);}
  win.addEventListener('resize',this.measure);
  this.refreshMode();this.render();this.measure();
 }
 refreshMode(){
  this.gate.setMode(this.elements('execute').checked,this.elements('batch-mode').checked,this.hasImages());
 }
 render(){
  if(!this.bar)return;
  const state=this.gate.snapshot;
  this.progress.setSuppressed?.(!!state.showBatch);
  const running=!!state.activeBatch||(state.localBusy&&state.busyKind==='running');
  const loading=state.localBusy&&!running;
  const failed=!state.showBatch&&['error','disconnected'].includes(this.progress.data?.state)&&!state.localBusy;
  this.bar.dataset.state=running?'running':loading?'loading':failed?'error':
   (['done','cancelled'].includes(this.progress.data?.state)||state.batchTerminal)?'complete':'idle';
  this.elements('reuse-analysis').disabled=!state.canSubmit;
  for(const id of ['batch-mode','prompt-only'])this.elements(id).disabled=!!(state.localBusy||state.activeBatch);
  const message=this.elements('run-loading-status');
  message.hidden=!loading;
  message.textContent=({loading:'設定を読み込んでいます。',preparing:'実行前チェックをしています。',submitting:'生成リクエストを送信しています。'})[state.busyKind]||'設定を確認しています。';
  const modeToggle=this.elements('expand-run-modes');if(modeToggle)modeToggle.hidden=this.bar.dataset.state!=='complete';
  const jump=this.bar.querySelector('.result-jump');
  if(jump)jump.hidden=!!state.showBatch;
  if(jump)jump.textContent=failed?'エラー内容を確認':this.bar.dataset.state==='complete'?'結果を見る':'結果へ移動';
 }
 focusStatus(){
  const active=this.doc.activeElement;
  if(active&&active!==this.doc.body&&!active.closest?.('.floating-runbar')&&active.id!=='reuse-analysis')return;
  this.doc.querySelector('#progress-state')?.focus({preventScroll:true});
 }
 destroy(){
  this.unsubscribeGate();this.unsubscribeProgress();this.observer?.disconnect();
  this.win.removeEventListener('resize',this.measure);
 }
}
