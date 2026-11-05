const {readProjectFile}=require('./support.cjs');
const vm=require('node:vm'),assert=require('node:assert/strict');
const form={elements:[
 {name:'cfg',type:'number',value:'5.5'},
 {name:'execute',type:'checkbox',checked:false},
 {name:'image',type:'file',value:'private-file.png'},
 {name:'restored_generation',type:'hidden',value:'{}'},
 {name:'',type:'text',value:'unnamed'},
 {name:'run',type:'submit',value:'submit'}
]};
const context=vm.createContext({$:()=>form});
vm.runInContext(readProjectFile('web/static/form_settings.js'),context);
const read=expression=>JSON.parse(JSON.stringify(vm.runInContext(expression,context)));
assert.deepEqual(read('readFormFields($("form"))'),{cfg:'5.5',execute:false,restored_generation:'{}'});
assert.deepEqual(read('readGenerationFields()'),{cfg:'5.5',execute:false});
assert.deepEqual(read('readFormFields($("form"),["cfg"])'),{cfg:'5.5'});
console.log('Shared form fields passed: numeric strings and unchecked flags retained; files, buttons and transient preset fields excluded.');
