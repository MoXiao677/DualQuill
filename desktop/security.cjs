'use strict';
const APP_URL = 'novel://app/';
const ASSETS = new Map(Object.entries({
  '/':'index.html','/app.js':'app.js','/api.js':'api.js','/state.js':'state.js',
  '/chat_workspace.js':'chat_workspace.js',
  '/layout.js':'layout.js','/views.js':'views.js','/knowledge.js':'knowledge.js','/i18n.js':'i18n.js','/provider_views.js':'provider_views.js',
  '/model_tasks.js':'model_tasks.js','/comparison_views.js':'comparison_views.js',
  '/deep_reviews.js':'deep_reviews.js',
  '/memory_automation.js':'memory_automation.js',
  '/graph_view.js':'graph_view.js',
  '/rule_reviews.js':'rule_reviews.js',
  '/workflow_views.js':'workflow_views.js','/style.css':'style.css',
  '/workflow_editor.js':'workflow_editor.js',
  '/sampling.js':'sampling.js',
  '/creative_dialogue.js':'creative_dialogue.js',
  '/author_scope.js':'author_scope.js',
  '/creation_presets.js':'creation_presets.js',
  '/book_creation.js':'book_creation.js',
  '/book_ai.js':'book_ai.js',
  '/styles.js':'styles.js',
  '/public_search.js':'public_search.js',
  '/style_trials.js':'style_trials.js',
  '/chapter_writing.js':'chapter_writing.js','/annotations.js':'annotations.js',
  '/writing_candidates.js':'writing_candidates.js',
  '/chapter_planning.js':'chapter_planning.js',
  '/model_planning.js':'model_planning.js',
  '/scene_expansion.js':'scene_expansion.js',
  '/migration.js':'migration.js',
  '/chapter_management.js':'chapter_management.js',
  '/provider_management.js':'provider_management.js',
  '/console.js':'console.js',
  '/console_usage.js':'console_usage.js',
  '/rules_scope.js':'rules_scope.js',
  '/materials.js':'materials.js',
  '/semantic_retrieval.js':'semantic_retrieval.js',
  '/full_book_planning.js':'full_book_planning.js',
  '/local_data.js':'local_data.js',
  '/favicon.svg':'favicon.svg','/guide.html':'guide.html'
}));
const CSP = "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none'; frame-ancestors 'none'; worker-src 'none'";
function classify(raw,method) {
  if(typeof raw!=='string'||raw.length>2048||!['GET','POST'].includes(method)||/[\\%?#]/.test(raw)||raw.includes('/../')||raw.includes('/./'))throw Error('Blocked request');
  const url=new URL(raw);
  if(url.protocol!=='novel:'||url.hostname!=='app'||url.port||url.username||url.password||url.hash||url.search)throw Error('Blocked origin');
  if(method==='GET'&&ASSETS.has(url.pathname))return {kind:'asset',file:ASSETS.get(url.pathname),path:url.pathname};
  if(!/^\/api\/(session|projects|settings|modules|skills|providers|tasks|backups|migrations|desktop)(\/[a-zA-Z0-9_-]+)*$/.test(url.pathname))throw Error('Blocked API');
  if(url.pathname==='/api/session'&&method!=='GET')throw Error('Blocked session');
  return {kind:'api',path:url.pathname};
}
function proxyHeaders(input,token,port,length) {
  const get=name=>input instanceof Headers?input.get(name):Object.entries(input).find(([k])=>k.toLowerCase()===name)?.[1];
  const headers={Host:'127.0.0.1:'+port,Origin:'http://127.0.0.1:'+port,'X-Novel-Token':token};
  for(const [name,out] of [['content-type','Content-Type'],['x-novel-backup-operation','X-Novel-Backup-Operation'],['x-novel-migration-operation','X-Novel-Migration-Operation'],['x-novel-migration-preview','X-Novel-Migration-Preview']]) {
    const value=get(name);if(value!==undefined&&value!==null){if(typeof value!=='string'||value.length>256||/[\r\n]/.test(value))throw Error('Blocked header');headers[out]=value;}
  }
  if(length!==undefined)headers['Content-Length']=String(length);
  return headers;
}
function assertSender(event,owner) {
  if(!owner||event.sender!==owner||event.senderFrame!==owner.mainFrame||event.senderFrame.url!==APP_URL)throw Error('Untrusted desktop IPC');
}
function downloadPath(value){
  if(typeof value!=='string'||!(/^\/api\/projects\/[a-zA-Z0-9_-]+\/export\/(book|volume|chapter)\/(txt|md)(\/[a-zA-Z0-9_-]+)?$/.test(value)||/^\/api\/backups\/download\/[a-zA-Z0-9_-]+$/.test(value)||/^\/api\/settings\/chat\/attachment\/[a-f0-9-]{36}\/download$/.test(value)))throw Error('Blocked download');
  classify(APP_URL.slice(0,-1)+value,'GET');return value;
}
module.exports={APP_URL,ASSETS,CSP,classify,proxyHeaders,assertSender,downloadPath};
