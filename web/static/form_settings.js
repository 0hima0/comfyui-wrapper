/* Canonical fields shared by presets and dependency checks. */
const GENERATION_FIELD_NAMES = [
 'target', 'checkpoint', 'profile', 'instruction', 'additional_positive', 'additional_negative',
 'rating', 'seed', 'sampler_name', 'scheduler', 'width', 'height', 'steps', 'cfg', 'denoise',
 'clip_skip', 'threshold', 'execute', 'use_wd', 'preserve_people', 'use_quality_tags'
];

function readFormFields(form, names = null){
 const fields = {};
 const allowed = names ? new Set(names) : null;
 for (const field of form.elements){
  if (!field.name || ['file', 'button', 'submit'].includes(field.type)) continue;
  if (allowed && !allowed.has(field.name)) continue;
  fields[field.name] = field.type === 'checkbox' ? field.checked : field.value;
 }
 return fields;
}

function readGenerationFields(){
 return readFormFields($('form'), GENERATION_FIELD_NAMES);
}
