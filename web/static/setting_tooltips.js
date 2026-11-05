/** Optional setting help, shown on hover/focus or pinned by touch/click. */
class SettingTooltips {
 constructor(doc=document,win=window){
  this.doc=doc;this.win=win;this.active=null;this.closeTimer=null;
  this.handlers={
   pointerover:event=>{
    if(event.pointerType==='touch')return;
    const trigger=event.target.closest?.('.help-trigger');
    if(trigger)this.show(trigger);
    else if(this.active?.tip.contains(event.target))this.cancelClose();
   },
   pointerout:event=>{
    if(!this.active||this.active.pinned)return;
    const next=event.relatedTarget;
    if(next&&(this.active.trigger.contains(next)||this.active.tip.contains(next)))return;
    if(this.active.trigger.contains(event.target)||this.active.tip.contains(event.target))this.scheduleClose();
   },
   focusin:event=>{const trigger=event.target.closest?.('.help-trigger');if(trigger)this.show(trigger);},
   focusout:event=>{
    if(!this.active||this.active.pinned)return;
    const next=event.relatedTarget;
    if(next&&(this.active.trigger.contains(next)||this.active.tip.contains(next)))return;
    if(this.active.trigger.matches(':hover')||this.active.tip.matches(':hover'))return;
    this.hide();
   },
   click:event=>{
    const trigger=event.target.closest?.('.help-trigger');
    if(trigger){
     event.preventDefault();
     if(this.active?.trigger===trigger&&this.active.pinned)this.hide();
     else this.show(trigger,true);
    }else if(this.active&&!this.active.tip.contains(event.target))this.hide();
   },
   keydown:event=>{if(event.key==='Escape'&&this.active){event.preventDefault();this.hide();}},
   scroll:event=>{if(this.active&&!this.active.tip.contains(event.target))this.position();},
   pagehide:()=>this.hide(),
   resize:()=>this.hide()
  };
  for(const type of ['pointerover','pointerout','focusin','focusout','click','keydown'])doc.addEventListener(type,this.handlers[type]);
  doc.addEventListener('scroll',this.handlers.scroll,true);
  for(const type of ['resize','pagehide'])win.addEventListener(type,this.handlers[type]);
 }
 static create(id,title,text,doc=document){
  const group=doc.createElement('span');group.className='help-anchor';
  const button=doc.createElement('button');button.type='button';button.className='help-trigger';
  button.dataset.tooltip=id;button.textContent='ⓘ';
  button.setAttribute('aria-label',title+'の説明');button.setAttribute('aria-describedby',id);button.setAttribute('aria-expanded','false');
  const tip=doc.createElement('span');tip.id=id;tip.className='setting-tooltip';tip.hidden=true;
  tip.setAttribute('role','tooltip');tip.textContent=text;group.append(button,tip);return group;
 }
 cancelClose(){this.win.clearTimeout(this.closeTimer);this.closeTimer=null;}
 scheduleClose(){this.cancelClose();this.closeTimer=this.win.setTimeout(()=>this.hide(),160);}
 show(trigger,pinned=false){
  this.cancelClose();
  if(this.active?.trigger===trigger){if(pinned)this.active.pinned=true;return;}
  this.hide();
  const tip=this.doc.getElementById(trigger.dataset.tooltip);if(!tip)return;
  this.active={trigger,tip,pinned};
  this.doc.body.append(tip);
  tip.hidden=false;tip.style.visibility='hidden';
  tip.style.maxHeight=Math.max(0,this.win.innerHeight-24)+'px';
  this.position();tip.style.visibility='';
  trigger.setAttribute('aria-expanded','true');
 }
 position(){
  if(!this.active)return;
  const {trigger,tip}=this.active;
  const anchor=trigger.getBoundingClientRect(),box=tip.getBoundingClientRect();
  if(anchor.bottom<0||anchor.top>this.win.innerHeight||anchor.right<0||anchor.left>this.win.innerWidth){this.hide();return;}
  const margin=12,gap=8;
  const left=Math.max(margin,Math.min(anchor.left,this.win.innerWidth-box.width-margin));
  const below=this.win.innerHeight-anchor.bottom-gap-margin,above=anchor.top-gap-margin;
  const preferred=box.height>below&&above>below?anchor.top-gap-box.height:anchor.bottom+gap;
  const top=Math.max(margin,Math.min(preferred,this.win.innerHeight-box.height-margin));
  tip.style.left=left+'px';tip.style.top=top+'px';
 }
 hide(){
  this.cancelClose();
  if(!this.active)return;
  this.active.tip.hidden=true;
  this.active.trigger.setAttribute('aria-expanded','false');
  this.active=null;
 }
 destroy(){
  this.hide();
  for(const type of ['pointerover','pointerout','focusin','focusout','click','keydown'])this.doc.removeEventListener(type,this.handlers[type]);
  this.doc.removeEventListener('scroll',this.handlers.scroll,true);
  for(const type of ['resize','pagehide'])this.win.removeEventListener(type,this.handlers[type]);
 }
}
const settingTooltips=new SettingTooltips();
