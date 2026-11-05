/* Normal generation, cached analysis, cancellation and progress monitoring. */
function initializeGenerationActions(){
 async function cancelJob(){
  if (!activeJob || $('cancel-job').disabled) return;
  $('cancel-job').disabled = true;
  try{
   const reply = await getJSON('/api/jobs/' + encodeURIComponent(activeJob) + '/cancel', {
    method: 'POST', headers: {'X-Requested-With': 'LLMPC'}
   });
   if (reply.cancel_requested){
    $('cancel-job').textContent = '停止処理中…';
    progressView.render({...progressView.data,cancel_requested:true,message:'停止処理中…（処理の終了を待っています）'});
   }
  }catch(error){
   $('cancel-job').disabled = false;
   status('停止要求を送信できませんでした。' + error.message, true);
  }
 }

 async function monitor(job, submitted=false){
  let wasRunning=submitted;
  for (;;){
   const data = await getJSON('/api/jobs/' + encodeURIComponent(job));
   if(data.state==='running'){wasRunning=true;generationGate.setLocalBusy(true,'running');}
   progressView.render(data);
   $('cancel-job').hidden = data.state !== 'running';
   $('cancel-job').disabled = !!data.cancel_requested;
   $('cancel-job').textContent = data.cancel_requested ? '停止処理中…' : '停止';
   status(data.state === 'error' ? data.message : '', data.state === 'error');
   if (data.state === 'done'){
    showResult(data);
    if(wasRunning && data.images?.length)showCompletionNotice();
    return;
   }
   if (data.state === 'error' || data.state === 'cancelled'){
    if (data.result && data.downloads) showResult(data);
    return;
   }
   await new Promise(resolve => setTimeout(resolve, 2000));
  }
 }

 function jobForm(reuse){
  $('loras').value = JSON.stringify(loraValues());
  const data = new FormData($('form'));
  referenceEditor.appendTo(data);
  if (reuse){
   if (!reuseSource) throw Error('再利用する解析結果がありません。');
   if ($('batch-mode').checked) throw Error('解析の再利用では連続生成モードをオフにしてください。');
   data.set('reuse_job_id', reuseSource);
   data.set('final_positive', $('positive').value);
   data.set('final_negative', $('negative').value);
  }
  const plan = batchPlan();
  if (plan) data.set('batch_plan', JSON.stringify(plan));
  return data;
 }

 function beginUpload(){
  referenceEditor.setDisabled(true);
  $('result').hidden = true;
  $('person-prompt-note').hidden = true;
  $('downloads').replaceChildren();
  $('generated-images').replaceChildren();
  $('empty').hidden = false;
  progressView.render({
   state: 'running', created_at: new Date().toISOString(), settings: {execute: $('execute').checked},
   progress: {stage: 'upload', detail: '指示・生成設定を送信しています…'}
  });
  status('');
 }

 async function submitGeneration(reuse = false){
  if ($('submit').disabled || !$('form').reportValidity()) return;
  if ($('generation-model').disabled || !$('checkpoint').value){
   status('モデル一覧の取得完了を待ち、チェックポイントを選択してください。', true);
   return;
  }
  generationGate.setLocalBusy(true,'preparing');
  let requestStarted = false, submittedJob = null;
  try{
   if (!await generationGate.refresh() || generationGate.activeBatch) return;
   const needsRegistry = $('target').value !== 'anima' && [0, 1, 2].some(i => $('lora-' + i).value);
   if (needsRegistry && !await registryReady){
    throw Error('LoRA登録情報を取得できません。トリガーワード管理から一覧を更新してください。');
   }
   await saveWorkspace();
   const data = jobForm(reuse);
   if (!await checkDependencies(reuse)){
    throw Error('実行前チェックで問題が見つかりました。専用ページで詳細を確認してください。');
   }
   generationGate.setLocalBusy(true,'submitting');
   beginUpload();
   requestStarted = true;
   let requestId=sessionStorage.getItem?.('llmpc-pending-submission');
   if(!requestId){
    const bytes=new Uint8Array(16);crypto.getRandomValues(bytes);
    requestId=Array.from(bytes,value=>value.toString(16).padStart(2,'0')).join('');
    sessionStorage.setItem('llmpc-pending-submission',requestId);
   }
   const reply = await getJSON('/api/jobs', {
    method: 'POST', headers: {'X-Requested-With': 'LLMPC','X-Request-ID':requestId}, body: data
   });
   if(!reply?.job_id&&!reply?.batch_id)throw Error('受付結果を読み取れません。同じ受付IDで再確認してください。');
   sessionStorage.removeItem('llmpc-pending-submission');
   if (reply.batch_id){
    generationGate.markBatch(reply.batch_id);
    sessionStorage.removeItem('llmpc-job');
    window.location.assign('/batch/' + encodeURIComponent(reply.batch_id));
    return;
   }
   submittedJob = activeJob = reply.job_id;
   generationGate.setLocalBusy(true,'running');
   if(typeof focusRunStatus==='function')focusRunStatus();
   sessionStorage.setItem('llmpc-job', activeJob);
   await monitor(activeJob, true);
  }catch(error){
   if(error.httpStatus && error.httpStatus<500)sessionStorage.removeItem('llmpc-pending-submission');
   if (reuse && !submittedJob) $('result').hidden = false;
   status(error.message, true);
   if (submittedJob) progressView.disconnected(error.message);
   else if (requestStarted){
    progressView.render({...progressView.data, state: 'error', message: error.message, finished_at: new Date().toISOString()});
   }
  }finally{
   $('cancel-job').hidden = true;
   referenceEditor.setDisabled(false);
   generationGate.setLocalBusy(false);
  }
 }

 // Implicit submission (Enter in a text field) must never start a job.
 $('form').addEventListener('submit', event => event.preventDefault());
 $('submit').addEventListener('click', () => submitGeneration(false));
 $('reuse-analysis').addEventListener('click', () => submitGeneration(true));
 $('cancel-job').addEventListener('click', cancelJob);
 return {monitor, submitGeneration};
}
