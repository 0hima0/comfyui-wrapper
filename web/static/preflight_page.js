const state=new WorkspaceState();
$('check-dependencies').addEventListener('click',async()=>{
 const button=$('check-dependencies');button.disabled=true;
 $('preflight-results').replaceChildren();
 try{
  const snapshot=state.read();
  if(!snapshot?.fields?.checkpoint)throw Error('生成画面でモデル・設定を指定してください。');
  const fields=Object.fromEntries(Object.entries(snapshot.fields).filter(([key])=>GENERATION_FIELD_NAMES.includes(key)));
  const files=await state.files();
  const ids=(snapshot.references||[]).filter(ref=>files.some(row=>row.id===ref.id&&row.filename===ref.filename)).map(row=>row.id);
  $('checked-settings').textContent=fields.checkpoint+' ／ '+(fields.execute?'画像生成':'Prompt・ワークフローのみ')+' ／ 参考画像 '+ids.length+'枚';
  $('preflight-status').textContent='確認中…';
  const result=await getJSON('/api/preflight',{method:'POST',headers:{'Content-Type':'application/json','X-Requested-With':'LLMPC'},body:JSON.stringify({fields,loras:snapshot.loras||[],reference_ids:ids,restored_generation:JSON.parse(snapshot.fields.restored_generation||'{}')})});
  for(const row of result.checks){const item=document.createElement('li');item.textContent=(row.ok?'✓ ':'要確認：')+row.name+'：'+row.detail;$('preflight-results').append(item);}
  $('preflight-status').textContent=result.ok?'実行に必要な設定を確認しました。':'確認が必要な項目があります。';
 }catch(error){$('preflight-status').textContent=error.message;}
 finally{button.disabled=false;}
});