/** Search the complete saved collection; never just filter loaded cards. */
const galleryFilterKeys=['q','model','lora','label','after','before'];
function galleryFilters(){const params=new URLSearchParams(location.search),result=new URLSearchParams();for(const key of galleryFilterKeys){const value=params.get(key);if(value)result.set(key,value);}return result.toString();}
const gallerySearch=$('gallery-search');
if(gallerySearch){
 for(const key of galleryFilterKeys)gallerySearch.elements.namedItem(key).value=new URLSearchParams(location.search).get(key)||'';
 const search=()=>{const url=new URL(location.href);for(const key of galleryFilterKeys){const value=gallerySearch.elements.namedItem(key).value.trim();if(value)url.searchParams.set(key,value);else url.searchParams.delete(key);}history.replaceState(null,'',url);galleryComparison.selected.clear();galleryComparison.sync();loadGallery(true);};
 gallerySearch.addEventListener('submit',event=>{event.preventDefault();if(!galleryBusy&&!favoriteBusy)search();});
 $('clear-gallery-search').addEventListener('click',()=>{if(galleryBusy||favoriteBusy)return;gallerySearch.reset();search();});
}
let annotationTarget=null,annotationBusy=false;
function annotationSummary(item,node){node.replaceChildren();const data=item.annotation||{};if(data.note){const note=document.createElement('p');note.className='image-note';note.textContent=data.note;node.append(note);}for(const value of data.labels||[]){const chip=document.createElement('span');chip.className='image-label';chip.textContent=value;node.append(chip);}}
function addAnnotationEditor(item,body,actions){
 const summary=document.createElement('div');summary.className='image-annotation';annotationSummary(item,summary);body.append(summary);
 const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent='メモ・分類';button.addEventListener('click',()=>{annotationTarget={item,summary};$('annotation-name').textContent=item.comfy_filename||item.filename;$('annotation-note').value=item.annotation?.note||'';$('annotation-labels').value=(item.annotation?.labels||[]).join(', ');$('annotation-status').textContent='';$('annotation-dialog').showModal();});actions.append(button);
}
$('annotation-close').addEventListener('click',()=>$('annotation-dialog').close());
$('annotation-dialog').addEventListener('cancel',event=>{if(annotationBusy)event.preventDefault();});
$('annotation-save').addEventListener('click',async()=>{
 if(!annotationTarget||annotationBusy)return;annotationBusy=true;$('annotation-save').disabled=true;$('annotation-close').disabled=true;
 const {item,summary}=annotationTarget;
 try{const data=await getJSON('/api/gallery/'+encodeURIComponent(item.job_id)+'/'+encodeURIComponent(item.filename)+'/annotation',{method:'PUT',headers:{'Content-Type':'application/json','X-Requested-With':'LLMPC'},body:JSON.stringify({note:$('annotation-note').value,labels:$('annotation-labels').value.split(/[,、\n]/).map(x=>x.trim()).filter(Boolean)})});item.annotation=data;annotationSummary(item,summary);$('annotation-dialog').close();}
 catch(error){$('annotation-status').textContent=error.message;}finally{annotationBusy=false;$('annotation-save').disabled=false;$('annotation-close').disabled=false;}
});
