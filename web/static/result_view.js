/* Display generated artifacts without managing jobs or workspace persistence. */
function openImageViewer(url, name){
 $('viewer-image').src = url;
 $('viewer-name').textContent = name;
 $('image-viewer').showModal();
}

function renderPromptConflicts(conflicts = {}){
 const removed = [...(conflicts.removed_wd_tags || []), ...(conflicts.removed_generated_tags || [])];
 $('conflicts').textContent = removed.length
  ? '入力プロンプトを優先して除外したタグ：' + [...new Set(removed.map(item => item.tag))].join(', ')
  : '競合ルールで除外したタグはありません。';
}

function renderGeneratedImages(data){
 $('generated-images').replaceChildren();
 for (const name of data.images || []){
  if(!data.downloads[name])continue;
  const preview = document.createElement('button');
  preview.type = 'button';
  preview.className = 'image-preview';
  preview.setAttribute('aria-label', name + 'を拡大表示');
  const url = data.downloads[name] + '?inline=1';
  preview.addEventListener('click', () => openImageViewer(url, name));
  const image = document.createElement('img');
  image.src = url;
  image.alt = 'ComfyUIの生成結果';
  image.className = 'generated-result-image';
  preview.append(image);
  const caption = document.createElement('p');
  caption.className = 'hint';
  const output = (data.output_files || []).find(item => item.webui_filename === name);
  caption.textContent = 'WebUI：' + name + (output
   ? ' ／ ComfyUI：' + [output.comfy_subfolder, output.comfy_filename].filter(Boolean).join('/') : '');
  $('generated-images').append(preview, caption);
 }
}

function renderDownloadLinks(data){
 $('downloads').replaceChildren();
 const artifacts = [
  ...(data.images || []).map(name => [name, '画像を保存：' + name]),
  ['workflow.json', 'ワークフローJSON'], ['results.zip', 'すべてをZIPで保存'], ['analysis.json', '解析結果JSON']
 ];
 for (const [name, label] of artifacts){
  if(!data.downloads[name])continue;
  const link = document.createElement('a');
  link.className = 'download';
  link.href = data.downloads[name];
  link.textContent = label;
  link.download = name;
  $('downloads').append(link);
 }
 if(data.zip_error||(!data.downloads['results.zip']&&!data.temporary)){
  const warning=document.createElement('p');warning.className='status error';warning.setAttribute('role','status');
  warning.textContent=data.zip_error||'ZIPがありません。個別の成果物を保存するか、ZIPを再作成してください。';
  $('downloads').append(warning);
  if(!data.temporary){
   const retry=document.createElement('button');retry.type='button';retry.className='secondary';retry.textContent='ZIPを再作成';retry.disabled=!!data.zip_building;
   retry.addEventListener('click',async()=>{
    retry.disabled=true;warning.textContent='ZIPを再作成しています…';
    try{const updated=await getJSON('/api/jobs/'+encodeURIComponent(data.job_id)+'/archive',{method:'POST',headers:{'X-Requested-With':'LLMPC'}});if(retry.isConnected)renderDownloadLinks(updated);}
    catch(error){warning.textContent=error.message;retry.disabled=false;}
   });
   $('downloads').append(retry);
  }
 }
}

function showResult(data){
 reuseSource = data.job_id || activeJob;
 $('person-prompt-note').hidden = !data.settings?.preserve_people;
 renderPromptConflicts(data.prompt_conflicts);
 renderGeneratedImages(data);
 renderDownloadLinks(data);
 renderRecoveryActions(data);
 $('empty').hidden = true;
 $('result').hidden = false;
 $('summary').textContent = data.result.summary_ja;
 $('positive').value = data.result.positive;
 $('negative').value = data.result.negative;
 $('uncertainties').textContent = data.result.uncertainties_ja;
}

function renderRecoveryActions(data){
 let area=$('job-recovery');
 if(!area){area=document.createElement('section');area.id='job-recovery';$('result').append(area);}
 area.replaceChildren();
 if(!data.prompt_id||!['error','cancelled'].includes(data.state))return;
 const message=document.createElement('p');message.setAttribute('role','status');
 message.textContent='ComfyUIで処理が続いている可能性があります。再生成の前に状態を確認できます。';
 const check=document.createElement('button');check.type='button';check.className='secondary';check.textContent='ComfyUIの状態を再確認';
 const take=document.createElement('button');take.type='button';take.className='secondary';take.textContent='完成画像を取り込む';take.hidden=true;
 async function reconcile(importImages){
  check.disabled=take.disabled=true;
  try{
   const outcome=await getJSON('/api/jobs/'+encodeURIComponent(data.job_id)+'/reconcile',{
    method:'POST',headers:{'X-Requested-With':'LLMPC','Content-Type':'application/json'},body:JSON.stringify({import_images:importImages}),timeoutMs:120000
   });
   if(!area.isConnected)return;
   message.textContent=outcome.message;take.hidden=outcome.state!=='completed';
   if(outcome.state==='imported')showResult(await getJSON('/api/jobs/'+encodeURIComponent(data.job_id)));
  }catch(error){message.textContent=error.message;}
  finally{check.disabled=take.disabled=false;}
 }
 check.addEventListener('click',()=>reconcile(false));take.addEventListener('click',()=>reconcile(true));
 area.append(message,check,take);
}

function initializeResultView(){
 $('refresh-interrupted-history').addEventListener('click',async()=>{
  const button=$('refresh-interrupted-history');button.disabled=true;
  const message=$('interrupted-history-status');
  try{
   const data=await getJSON('/api/history?recoverable=1');
   const records=data.items.filter(row=>row.prompt_id&&['error','cancelled'].includes(row.state));
   const list=$('interrupted-history-list');list.replaceChildren();
   for(const row of records){const link=document.createElement('a');link.className='download secondary';link.href='/?restore='+encodeURIComponent(row.job_id);link.textContent=(row.created_at||row.job_id)+'：'+row.message;list.append(link);}
   message.textContent=records.length?records.length+'件。対象を開き、結果欄でComfyUIの状態を再確認してください。':'直近20件に照合可能な中断実行はありません。';
  }catch(error){message.textContent=error.message;}
  finally{button.disabled=false;}
 });
 $('close-viewer').addEventListener('click', () => $('image-viewer').close());
 $('image-viewer').addEventListener('click', event => {
  const rect = $('image-viewer').getBoundingClientRect();
  if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom){
   $('image-viewer').close();
  }
 });
 for (const button of document.querySelectorAll('[data-copy]')){
  button.addEventListener('click', async () => {
   const field = $(button.dataset.copy);
   try{
    if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(field.value);
    else{
     field.focus();
     field.select();
     if (!document.execCommand('copy')) throw Error();
    }
    button.textContent = 'コピーしました';
   }catch{
    field.focus();
    field.select();
    button.textContent = '選択しました。手動でコピー';
   }
   setTimeout(() => button.textContent = 'コピー', 2500);
  });
 }
}
