const systemTabs=[...document.querySelectorAll('[data-system-tab]')];
function selectSystemTab(key,focus=false){
 const chosen=systemTabs.find(tab=>tab.dataset.systemTab===key)||systemTabs[0];
 for(const tab of systemTabs){const selected=tab===chosen;tab.setAttribute('aria-selected',String(selected));tab.tabIndex=selected?0:-1;document.getElementById(tab.getAttribute('aria-controls')).hidden=!selected;}
 if(focus)chosen.focus();
 history.replaceState(null,'','#'+chosen.dataset.systemTab);
 document.title=chosen.textContent+' | システム管理 | ComfyUI Wrapper';
 document.dispatchEvent(new CustomEvent('system-tab-change',{detail:chosen.dataset.systemTab}));
}
for(const tab of systemTabs){
 tab.addEventListener('click',()=>selectSystemTab(tab.dataset.systemTab));
 tab.addEventListener('keydown',event=>{
  const index=systemTabs.indexOf(tab);let next;
  if(event.key==='ArrowRight')next=(index+1)%systemTabs.length;
  if(event.key==='ArrowLeft')next=(index-1+systemTabs.length)%systemTabs.length;
  if(event.key==='Home')next=0;
  if(event.key==='End')next=systemTabs.length-1;
  if(next!==undefined){event.preventDefault();selectSystemTab(systemTabs[next].dataset.systemTab,true);}
 });
}
window.addEventListener('hashchange',()=>selectSystemTab(location.hash.slice(1)));
selectSystemTab(location.hash.slice(1)||systemTabs.find(tab=>tab.getAttribute('aria-selected')==='true')?.dataset.systemTab);