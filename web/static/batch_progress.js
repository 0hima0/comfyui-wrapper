/** Shared progress view for generation and batch review pages. */
class BatchProgressView {
 constructor(root){this.root=root;this.data=null;}
 render(data,{id=null,cancelRequested=false}={}){
  this.data=data;
  const root=this.root,terminal=data.state!=='running',phase=data.active_job?.progress||{};
  const stages={analysis:'画像解析',compose:'Prompt作成',queue:'キュー待ち',generate:'画像生成',save:'保存'};
  const ending={review:'完了・選別待ち',cancelled:'停止済み',error:'エラー・選別待ち',interrupted:'中断・選別待ち'};
  root.hidden=false;root.dataset.state=data.state;
  root.querySelector('[data-batch-stage]').textContent=terminal?(ending[data.state]||'終了'):
   (data.current||1)+' / '+data.count+'回目 · '+(cancelRequested?'停止処理中':stages[phase.stage]||'準備中');
  const start=Date.parse(data.created_at),end=Date.parse(data.finished_at)||Date.now();
  const seconds=Math.max(0,Math.floor((end-start)/1000));
  root.querySelector('[data-batch-elapsed]').textContent=Number.isFinite(seconds)?
   '経過 '+Math.floor(seconds/60)+'分'+String(seconds%60).padStart(2,'0')+'秒':'';
  root.querySelector('[data-batch-detail]').textContent=(data.completed||0)+' / '+data.count+'回完了 · '+(phase.detail||data.message||'');
  const meter=root.querySelector('[data-batch-progress]');meter.hidden=terminal;
  const select=root.querySelector('[data-batch-select]');if(select)select.hidden=!terminal;
  meter.max=Math.max(1,data.count||1);meter.value=data.completed||0;
  const steps=root.querySelector('[data-batch-steps]');
  const measured=!terminal&&phase.stage==='generate'&&Number.isFinite(phase.current)&&Number.isFinite(phase.total)&&phase.total>0&&phase.current>=0&&phase.current<=phase.total;
  steps.hidden=!measured;steps.textContent=measured?'生成ステップ '+phase.current+' / '+phase.total+'（'+Math.floor(phase.current/phase.total*100)+'%）':'';
  const review=root.querySelector('[data-batch-review]');
  if(review&&id)review.href='/batch/'+encodeURIComponent(id);
  const stop=root.querySelector('[data-batch-stop]');
  stop.hidden=terminal;stop.disabled=cancelRequested;
  stop.textContent=cancelRequested?'停止処理中…':'連続生成を停止';
 }
 error(message){
  this.root.hidden=false;this.root.dataset.state='disconnected';
  this.root.querySelector('[data-batch-stage]').textContent='接続確認';
  this.root.querySelector('[data-batch-detail]').textContent=message;
  this.root.querySelector('[data-batch-progress]').hidden=true;
  this.root.querySelector('[data-batch-steps]').hidden=true;
 }
}
function observeFloatingProgress(root){
 if(!root?.getBoundingClientRect)return ()=>{};
 const measure=()=>{
  const rect=root.getBoundingClientRect();
  document.documentElement.style.setProperty('--batch-progress-offset',Math.ceil(rect.bottom+16)+'px');
 };
 const observer=typeof ResizeObserver==='undefined'?null:new ResizeObserver(measure);
 observer?.observe(root);window.addEventListener('resize',measure);measure();
 return ()=>{observer?.disconnect();window.removeEventListener('resize',measure);};
}
