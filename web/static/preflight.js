/* Automatic dependency validation; manual results live on /preflight. */
async function checkDependencies(reuse=false){
 const fields=readGenerationFields();
 const data=await getJSON('/api/preflight',{method:'POST',headers:{'Content-Type':'application/json','X-Requested-With':'LLMPC'},
 body:JSON.stringify({fields,restored_generation:JSON.parse($('restored-generation').value||'{}'),loras:loraValues(),reference_ids:referenceEditor.entries.filter(x=>x.file).map(x=>x.id),reuse_job_id:reuse?reuseSource:null})});
 if(!data.ok)throw Error(data.checks.filter(row=>!row.ok).map(row=>row.name+': '+row.detail).join('。')||'実行前チェックで問題が見つかりました。');
 return true;
}