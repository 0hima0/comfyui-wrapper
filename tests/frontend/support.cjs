const fs=require('node:fs'),path=require('node:path');
const projectRoot=path.resolve(__dirname,'../..');
const readProjectFile=(name,encoding='utf8')=>fs.readFileSync(path.join(projectRoot,name),encoding);
module.exports={readProjectFile,projectRoot};
