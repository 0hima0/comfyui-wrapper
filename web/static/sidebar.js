/* Shared navigation. Preference is local to this browser. */
(() => {
 const sidebar=document.getElementById('app-sidebar');
 if(!sidebar)return;
 const toggle=document.getElementById('sidebar-toggle');
 const mobile=document.querySelector('.sidebar-mobile-toggle');
 const backdrop=document.querySelector('.sidebar-backdrop');
 const key='comfyui-wrapper-sidebar-collapsed';
 const narrow=window.matchMedia('(max-width: 760px)');
 const compact=window.matchMedia('(min-width: 901px) and (max-width: 1250px)');
 let compactChoice=null;
 const isCollapsed=()=>compact.matches?(compactChoice??true):collapsed;
 let collapsed=false;
 try{collapsed=localStorage.getItem(key)==='1';}catch{}
 function render(){
  const effective=isCollapsed();
  document.body.classList.toggle('sidebar-collapsed',effective);
  const label=effective?'サイドバーを展開する':'サイドバーを折りたたむ';
  toggle.textContent=effective?'›':'‹';toggle.title=label;
  toggle.setAttribute('aria-label',label);toggle.setAttribute('aria-expanded',String(!effective));
 }
 function drawer(open,restoreFocus=false){
  document.body.classList.toggle('sidebar-mobile-open',open);
  backdrop.hidden=!open;mobile.setAttribute('aria-expanded',String(open));
  if(narrow.matches)sidebar.inert=!open;
  if(open)sidebar.querySelector('[aria-current="page"]')?.focus();
  else if(restoreFocus)mobile.focus();
 }
 toggle.addEventListener('click',()=>{
  if(narrow.matches){drawer(false,true);return;}
  if(compact.matches)compactChoice=!isCollapsed();else collapsed=!collapsed;render();
  try{localStorage.setItem(key,collapsed?'1':'0');}catch{}
 });
 mobile.addEventListener('click',()=>drawer(mobile.getAttribute('aria-expanded')!=='true',true));
 backdrop.addEventListener('click',()=>drawer(false,true));
 document.addEventListener('keydown',event=>{
  if(!narrow.matches||mobile.getAttribute('aria-expanded')!=='true')return;
  if(event.key==='Escape'){drawer(false,true);event.preventDefault();}
  if(event.key==='Tab'){
   const controls=[...sidebar.querySelectorAll('a[href],button')];
   const first=controls[0],last=controls[controls.length-1];
   if(event.shiftKey&&document.activeElement===first){last.focus();event.preventDefault();}
   else if(!event.shiftKey&&document.activeElement===last){first.focus();event.preventDefault();}
  }
 });
 function resize(){drawer(false);sidebar.inert=narrow.matches;render();}
 narrow.addEventListener('change',resize);
 compact.addEventListener('change',()=>{compactChoice=null;resize();});
 document.addEventListener('sidebar-page',event=>{
  for(const link of sidebar.querySelectorAll('[data-sidebar-page]')){
   if(link.dataset.sidebarPage===event.detail)link.setAttribute('aria-current','page');
   else link.removeAttribute('aria-current');
  }
 });
 render();resize();
})();
