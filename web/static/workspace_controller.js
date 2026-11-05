/* Restore and persist the workspace independently of rendering and submission. */
let workspaceEdited = false;
function markWorkspaceEdited(){if(workspaceReady)workspaceEdited=true;}
function saveWorkspace(){
 if(!workspaceReady)return Promise.resolve();
 const fields=readFormFields($('form'));
 const references=referenceEditor.entries.map(row=>({id:row.id,filename:row.filename,role:row.role,size:row.file?.size,lastModified:row.file?.lastModified}));
 try{return workspaceState.save({edited:workspaceEdited,fields,loras:loraValues(),references,nextReferenceId:referenceEditor.nextId,resultDraft:reuseSource?{job_id:reuseSource,positive:$('positive').value,negative:$('negative').value}:null},referenceEditor.entries).catch(()=>{$('restored-note').textContent='参考画像をブラウザーに一時保存できませんでした。画面移動後に画像の再選択が必要になる場合があります。';});}
 catch{$('restored-note').textContent='このブラウザーでは画面の一時保存ができません。保存領域の設定を確認してください。';return Promise.resolve();}
}
function referencesChanged(entries){markWorkspaceEdited();updateLoraScopes(entries);refreshPersonState(entries);queueMicrotask(()=>{if(typeof syncExecutionChrome==='function')syncExecutionChrome();});saveWorkspace();}
async function restoreWorkspace(){
 const snapshot=workspaceState.read();if(!snapshot?.fields)return false;
 const fields=snapshot.fields;const warnings=[];
 let index=availableModels.findIndex(row=>row.name===fields.checkpoint&&row.target===fields.target);
 if(index<0&&fields.checkpoint){index=availableModels.length;availableModels.push({name:fields.checkpoint,target:fields.target});const option=document.createElement('option');option.value=String(index);option.textContent=fields.checkpoint+'（現在の一覧にありません）';$('generation-model').append(option);warnings.push('生成モデルが現在の一覧にありません');}
 if(index>=0){$('generation-model').value=String(index);$('profile').value=fields.profile||'auto';chooseModel();}
 for(const [name,value] of Object.entries(fields)){const field=$('form').elements.namedItem(name);if(!field||['checkpoint','target'].includes(name))continue;if(field.type==='checkbox')field.checked=Boolean(value);else if(field.tagName==='SELECT')selectValue(field,value);else field.value=value;}
 if($('use-wd').disabled&&$('use-wd').checked){$('use-wd').checked=false;if($('form').elements.namedItem('rating').value==='auto')$('form').elements.namedItem('rating').value='none';warnings.push('WDモデルが利用できないためWDをオフにしました');}
 $('use-wd').dispatchEvent(new Event('change'));toggleAdditionalPrompts();syncBatchOptions();restoreLoras(snapshot.loras||[]);
 let savedFiles=[];try{savedFiles=await workspaceState.files();}catch{warnings.push('参考画像の一時保存を読み込めません');}
 const references=(snapshot.references||[]).map(row=>({...row,file:savedFiles.find(saved=>saved.id===row.id&&saved.filename===row.filename&&saved.file?.size===row.size&&saved.file?.lastModified===row.lastModified)?.file||null}));
 referenceEditor.restore(references,true);referenceEditor.nextId=Math.max(referenceEditor.nextId,snapshot.nextReferenceId||1);
 workspaceEdited=snapshot.edited ?? Boolean(fields.instruction||fields.additional_positive||references.length||snapshot.loras?.length);
 refreshPersonState();
 if(references.some(row=>!row.file))warnings.push('参考画像を再選択してください');
 $('restored-note').textContent='画面移動前の入力内容を復元しました。'+(warnings.length?' '+warnings.join('。')+'。':'');return true;
}

async function initializeWorkspace(){
 await Promise.all([loadModels(),loadGenerationOptions()]);
 let restored=false;try{restored=await restoreWorkspace();}catch{$('restored-note').textContent='一時保存の復元に失敗しました。参考画像と設定を確認してください。';}
 workspaceReady=true;
 initializePresets();
 generationGate.setLocalBusy(false);
 const previous=sessionStorage.getItem('llmpc-job');
 if(previous&&!restored){try{selectedHistory=await getJSON('/api/history/'+encodeURIComponent(previous));await restoreHistory();}catch{$('restored-note').textContent='前の実行設定を取得できませんでした。参考画像と設定を確認してください。';}}
 if(previous){activeJob=previous;generationGate.setLocalBusy(true);referenceEditor.setDisabled(true);try{await monitor(previous);}catch{progressView.disconnected('前の処理の進捗を取得できませんでした。');status('前の処理の進捗を取得できません。接続を確認して再読込してください。',true);}finally{generationGate.setLocalBusy(false);referenceEditor.setDisabled(false);}}
 const draft=workspaceState.read()?.resultDraft;
 if(draft&&draft.job_id===reuseSource){$('positive').value=draft.positive;$('negative').value=draft.negative;}
 const restoreId=new URLSearchParams(window.location.search).get('restore');
 if(restoreId){
  try{
   selectedHistory=await getJSON('/api/history/'+encodeURIComponent(restoreId));
   if(await restoreHistory(true)){const saved=await getJSON('/api/jobs/'+encodeURIComponent(restoreId));if(saved.result&&saved.downloads){progressView.render(saved);showResult(saved);activeJob=restoreId;sessionStorage.setItem('llmpc-job',restoreId);}await saveWorkspace();window.history.replaceState(null,'',window.location.pathname);}
  }catch(error){$('restored-note').textContent='ギャラリーの設定を復元できませんでした。'+error.message;}
  finally{window.history.replaceState(null,'',window.location.pathname);}
 }
}
