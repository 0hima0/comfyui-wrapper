/** Own reference files, stable IDs, object URLs, and history reselection. */
class ReferenceEditor {
  constructor({input, drop, list, count, message, maxImages, onChange}) {
    Object.assign(this, {input, drop, list, count, message, maxImages, onChange});
    this.entries = [];
    this.nextId = 1;
    this.disabled = false;
    input.addEventListener('change', () => { this.addFiles(input.files); input.value = ''; });
    for (const event of ['dragenter','dragover']) drop.addEventListener(event, e => {
      e.preventDefault(); if (!this.disabled) drop.classList.add('drag');
    });
    for (const event of ['dragleave','drop']) drop.addEventListener(event, e => {
      e.preventDefault(); drop.classList.remove('drag');
    });
    drop.addEventListener('drop', event => this.addFiles(event.dataTransfer.files));
    this.render();
  }

  validate(entries) {
    if (entries.length > this.maxImages) throw Error(`参考画像は最大${this.maxImages}枚です。`);
    const files = entries.map(entry => entry.file).filter(Boolean);
    if (files.some(file => !['image/png','image/jpeg','image/webp'].includes(file.type) &&
        !(file.type === '' && /\.(png|jpe?g|webp)$/i.test(file.name))))
      throw Error('PNG・JPEG・WebPの画像を選択してください。');
    if (files.reduce((total,file) => total + file.size, 0) > 25*1024*1024)
      throw Error('参考画像の合計は25MB以内にしてください。');
  }

  addFiles(files) {
    if (this.disabled || !files.length) return;
    const planned = this.entries.map(entry => ({...entry}));
    let nextId = this.nextId;
    for (const file of files) {
      const empty = planned.find(entry => !entry.file && entry.filename === file.name);
      if (empty) empty.file = file;
      else planned.push({id:nextId++, filename:file.name, role:'', file});
    }
    try {
      this.validate(planned);
      for (const entry of planned) if (entry.file && !entry.url) entry.url = URL.createObjectURL(entry.file);
      this.entries = planned;
      this.nextId = nextId;
      this.render();
      this.message.textContent = '画像番号で、使う要素・使わない要素を指示してください。';
    } catch (error) { this.message.textContent = error.message; }
  }

  replace(id, file) {
    if (!file || this.disabled) return;
    const planned = this.entries.map(entry => entry.id === id ? {...entry, file, filename:file.name} : entry);
    try {
      this.validate(planned);
      const old = this.entries.find(entry => entry.id === id);
      if (!old) return;
      const url = URL.createObjectURL(file);
      if (old.url) URL.revokeObjectURL(old.url);
      Object.assign(planned.find(entry => entry.id === id), {url});
      this.entries = planned;
      this.render();
      this.message.textContent = `画像${id}を差し替えました。番号と使う要素は維持しています。`;
    } catch (error) { this.message.textContent = error.message; }
  }

  remove(id) {
    if (this.disabled) return;
    const entry = this.entries.find(entry => entry.id === id);
    if (entry?.url) URL.revokeObjectURL(entry.url);
    this.entries = this.entries.filter(entry => entry.id !== id);
    this.render();
    this.message.textContent = `画像${id}を削除しました。他の画像番号は変わりません。指示文の参照先を確認してください。`;
  }

  restore(descriptions, keepFiles=false) {
    if(keepFiles)this.validate(descriptions);
    for (const entry of this.entries) if (entry.url) URL.revokeObjectURL(entry.url);
    this.entries = descriptions.map(entry => ({id:entry.id, filename:entry.filename, role:entry.role||'', file:keepFiles?entry.file||null:null}));
    for(const entry of this.entries)if(entry.file)entry.url=URL.createObjectURL(entry.file);
    this.nextId = Math.max(0,...this.entries.map(entry=>entry.id)) + 1;
    this.input.value = '';
    this.render();
    this.message.textContent = keepFiles&&this.entries.every(entry=>entry.file)?'参考画像と使う要素を復元しました。':'使う要素と画像番号を復元しました。同名ファイルをまとめて追加するか、各行から画像を再選択してください。';
  }

  appendTo(formData) {

    const missing = this.entries.filter(entry => !entry.file);
    if (missing.length) throw Error(missing.map(entry=>'画像'+entry.id).join('・')+'を再選択してください。');
    this.validate(this.entries);
    formData.delete('image');
    for (const entry of this.entries) formData.append('image', entry.file, entry.file.name);
    formData.set('reference_info', JSON.stringify(this.entries.map(entry=>({id:entry.id,role:entry.role}))));
  }

  setDisabled(disabled) {
    this.disabled = disabled;
    this.input.disabled = disabled;
    for (const field of this.list.querySelectorAll('button,input')) field.disabled = disabled && !field.className?.includes('reference-preview');
  }

  render() {
    this.list.replaceChildren();
    this.count.textContent = `${this.entries.length} / ${this.maxImages}枚`;
    for (const entry of this.entries) {
      const row = document.createElement('div'); row.className = 'reference-item';
      const thumb = document.createElement('div'); thumb.className = 'reference-thumb';
      if (entry.url) {
        const img = document.createElement('img'); img.src = entry.url; img.alt = '画像'+entry.id+'のプレビュー';
        const preview=document.createElement('button');preview.type='button';preview.className='reference-preview';
        preview.setAttribute('aria-label','画像'+entry.id+'を拡大表示');preview.title='クリックで拡大表示';
        preview.append(img);thumb.append(preview);
        preview.addEventListener('click',()=>openImageViewer(entry.url,'画像'+entry.id+'：'+entry.filename));
      } else thumb.textContent = '再選択';
      const content = document.createElement('div'); content.className = 'reference-content';
      const title = document.createElement('strong'); title.textContent = '画像'+entry.id;
      const filename = document.createElement('div'); filename.className = 'hint';
      filename.textContent = entry.filename + (entry.file ? '' : '（再選択してください）');
      const label = document.createElement('label'); label.className = 'field'; label.textContent = '使う要素（任意）';
      const role = document.createElement('input'); role.type = 'text'; role.maxLength = 1000;
      role.value = entry.role; role.placeholder = '人物・服装・背景・画風など';
      role.addEventListener('input', () => entry.role = role.value); label.append(role);
      const roleHelp=document.createElement('span');roleHelp.className='field-help';roleHelp.id='help-reference-role-'+entry.id;
      roleHelp.textContent='この画像から使いたい要素を指定します。空欄でも利用でき、複数画像の指示では画像番号で対象を区別できます。';
      role.setAttribute('aria-describedby',roleHelp.id);label.append(roleHelp);
      const actions = document.createElement('div'); actions.className = 'reference-actions';
      const replacement = document.createElement('input'); replacement.type = 'file'; replacement.accept = this.input.accept; replacement.hidden = true;
      replacement.addEventListener('change', () => this.replace(entry.id, replacement.files[0]));
      const choose = document.createElement('button'); choose.type = 'button'; choose.className = 'secondary';
      choose.textContent = entry.file ? '差し替え' : '画像を再選択'; choose.setAttribute('aria-label','画像'+entry.id+'を再選択');
      choose.addEventListener('click', () => replacement.click());
      const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'secondary';
      remove.textContent = '削除'; remove.setAttribute('aria-label','画像'+entry.id+'を削除');
      remove.addEventListener('click', () => this.remove(entry.id));
      if(entry.url){const preview=document.createElement('button');preview.type='button';preview.className='secondary reference-preview-action';preview.textContent='プレビュー';preview.setAttribute('aria-label','画像'+entry.id+'のプレビューを開く');preview.addEventListener('click',()=>openImageViewer(entry.url,'画像'+entry.id+'：'+entry.filename));actions.append(preview);}
      actions.append(choose,remove,replacement); content.append(title,filename,label,actions); row.append(thumb,content); this.list.append(row);
    }
    this.setDisabled(this.disabled);
    this.onChange?.(this.entries);
  }
}
