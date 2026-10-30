import assert from 'node:assert/strict';
import { test } from 'node:test';
class Element {
  constructor(tag='fragment') { this.tag=tag; this.children=[]; this.dataset={}; this.style={}; this.className=''; this.listeners={}; this.classList={add(){},remove(){},toggle(){}}; }
  append(...items) { this.children.push(...items.flat()); }
  setAttribute(name,value) { this[name]=value; }
  addEventListener(name, listener) { this.listeners[name]=listener; }
  focus() { document.activeElement=this; }
  getBoundingClientRect() { return {left:100,top:100,width:400,height:380}; }
  get offsetWidth() { return 400; }
  get offsetHeight() { return 380; }
  setPointerCapture() {}
  remove() { this.removed=true; }
}
globalThis.Node=Element;
globalThis.cancelAnimationFrame=()=>{};
globalThis.document={documentElement:{dataset:{platform:"mac"}},createElement:tag=>new Element(tag),createDocumentFragment:()=>new Element(),createTextNode:text=>text};
globalThis.window={getSelection:()=>({isCollapsed:true}),addEventListener(){},removeEventListener(){}};
globalThis.innerWidth=800;globalThis.innerHeight=600;
document.body=new Element();
const { analyzeDocument, analyzeDocling }=await import('../../src/paperdesk/web/static/js/layout.js');
const { Visuals }=await import('../../src/paperdesk/web/static/js/visuals.js');
const { CitationPreview }=await import('../../src/paperdesk/web/static/js/references.js');
const { TranslationController }=await import('../../src/paperdesk/web/static/js/translation.js');
const { AssistantPanel }=await import('../../src/paperdesk/web/static/js/assistant.js');
const { Annotations }=await import('../../src/paperdesk/web/static/js/annotations.js');
const { LibraryView, paperDetails }=await import('../../src/paperdesk/web/static/js/library.js');
const { BackgroundImport }=await import('../../src/paperdesk/web/static/js/background.js');
const { TextMap }=await import('../../src/paperdesk/web/static/js/textmap.js');
const { extractPdfTitle }=await import('../../src/paperdesk/web/static/js/pdf.js');
function clock() {
  let now=0, id=0; const timers=new Map(), original=[globalThis.setTimeout,globalThis.clearTimeout];
  globalThis.setTimeout=(fn,delay)=>{timers.set(++id,{fn,time:now+delay});return id;};
  globalThis.clearTimeout=id=>timers.delete(id);
  return {tick(ms){now+=ms; for(const [id,t] of timers) if(t.time<=now){timers.delete(id);t.fn();}},restore(){[globalThis.setTimeout,globalThis.clearTimeout]=original;}};
}
for (const [name, Class, method] of [['equation',Visuals,'scheduleHide'],['citation',CitationPreview,'scheduleHide'],['paragraph',TranslationController,'scheduleHideHover']]) {
  test(name+' closes while the pointer keeps moving outside',()=>{
    const c=clock(); try {
      const controller=Object.create(Class.prototype); let hidden=false;
      controller.box={remove(){hidden=true;}};controller.popover={};controller.hover={classList:{remove(){hidden=true;}}};controller.hide=()=>{hidden=true;};
      controller[method]();
      for(let i=0;i<8;i++){c.tick(20);controller[method]();}
      assert.equal(hidden,true);
    } finally {c.restore();}
  });
}
test('moving over one reference does not postpone its preview',()=>{
  const c=clock();try{
    const preview=Object.create(CitationPreview.prototype);preview.reader={alive:true};let shown=0;preview.show=()=>shown++;
    const hit={spot:{}};
    for(let i=0;i<12;i++){preview.schedule(hit);c.tick(20);}
    assert.equal(shown,1);
  }finally{c.restore();}
});
test('a cross-page reference crops artwork separately from the caption',async()=>{
  const visual=Object.create(Visuals.prototype);let calls=[];
  visual.reader={alive:true,cropImage:async(...args)=>{calls.push(args);return 'image';},flashRect(){assert.fail('hover must not flash');}};
  visual.images=new Map();
  const target={kind:'figure',label:'1',page:2,rect:[0,0,1,1],imageRect:[0,0,1,.5],caption:'Full caption'};
  const content=visual.previewContent(target,1);assert.equal(content.children[1].tag,'img');
  await visual.imageFor(target);assert.equal(calls.length,1);assert.deepEqual(calls[0][1],target.imageRect);
});
test('translated equation references keep their math wrapper and reference number',()=>{
  const translation=Object.create(TranslationController.prototype);
  const result=translation.linkText('그림 1, 식 \\(3\\), Eq. $4$, [7, 8]');
  const refs=result.children.filter(n=>n instanceof Element && n.className==='xref');
  assert.deepEqual(refs.map(n=>[n.dataset.kind,n.dataset.label]),[['figure','1'],['equation','3'],['equation','4'],['cite','7, 8']]);
});
test('text-free artwork above a caption is included and final caption keys match',()=>{
  function item(str,top,size=10){return {str,height:size,width:480,transform:[size,0,0,size,60,800-top]};}
  const pages=[{width:600,height:800,items:[item('A paper with enough text to establish the body font.',120)]},
    {width:600,height:800,items:[item('Figure 1. First observation. Another caption sentence.',300),item('This paragraph is ordinary body text after the figure.',380),item('It continues on the following line with more evidence.',392)]}];
  const doc=analyzeDocument(pages), region=doc.regions[0];assert.ok(region);
  const caption=doc.blocks.find(b=>b.kind==='caption');
  assert.equal(region.captionKey,caption.key);assert.ok(region.imageRect[1]<.1);assert.ok(region.imageRect[3]<caption.rect[1]);assert.equal(region.rect[3],caption.rect[3]);
});
for(const [name,mode,provider,jobs,saved,expected] of [
  ['all body pages','side','demo',[],{},['first','second']],
  ['saved paragraphs reused','side','demo',[],{first:{}},['second']],
  ['fully translated document','side','demo',[],{first:{},second:{}},[]],
  ['hidden translations','off','demo',[],{},[]],
  ['no provider','side','',[],{},[]],
  ['paused job','side','demo',[{state:'paused',language:'Korean'}],{},[]],
  ['cancelled job','side','demo',[{state:'cancelled',language:'Korean'}],{},[]],
  ['failed job','side','demo',[{state:'failed',language:'Korean'}],{},[]],
  ['active job','side','demo',[{state:'running',language:'Korean'}],{},[]],
]) test('automatic translation: '+name,async()=>{
  const c=Object.create(TranslationController.prototype);let requested=[];
  c.reader={id:'paper',alive:true,current:1,tmode:mode,pages:[],nav:{refreshSections(){}},analysis:{blocks:[
    {key:'first',page:1,translatable:true}, {key:'second',page:2,translatable:true},
    {key:'reference',page:3,translatable:false}, {key:'equation',page:2,translatable:false}, {key:'footer',page:1,translatable:false}
  ]}};
  c.app={settings:{data:{provider,auto_translate:true},active:()=>provider?{available:true}:null},api:{get:async()=>({language:'Korean',blocks:saved})}};c.pending=new Set();
  c.pollJobs=async()=>{c.jobs=jobs;return true;};c.enqueue=async blocks=>{requested=blocks.map(b=>b.key);};
  await c.onAnalysis();assert.deepEqual(requested,expected);
});
test('translation cards remain inside the PDF page height',()=>{
  const c=Object.create(TranslationController.prototype);c.reader={alive:true,tmode:'side'};
  const card={dataset:{key:'first'},style:{},offsetHeight:1500};const state={el:{offsetHeight:800},tcol:{children:[card],style:{}}};
  c.placeCards(state,[{key:'first',rect:[0,.1,1,.2]}]);assert.equal(state.tcol.style.height,'800px');assert.equal(card.style.top,'0px');
});
test('translation cards stack without the gaps between source paragraphs',()=>{
  const c=Object.create(TranslationController.prototype);c.reader={alive:true,tmode:'side'};
  const first={dataset:{key:'a'},style:{},offsetHeight:40},second={dataset:{key:'b'},style:{},offsetHeight:30};
  const state={el:{offsetHeight:800},tcol:{children:[first,second],style:{}}};
  c.placeCards(state,[{key:'a',rect:[0,.1,1,.2]},{key:'b',rect:[0,.6,1,.7]}]);
  assert.equal(first.style.top,'0px');assert.equal(second.style.top,'46px');
});
test('moving from a heading into its button cancels the hide deadline',()=>{
  const c=clock();try {
    const translation=Object.create(TranslationController.prototype);translation.reader={area:{active:false},analysis:{}};
    let hidden=false;translation.hover={classList:{remove(){hidden=true;}}};translation.scheduleHideHover();
    c.tick(80);
    const button={closest:selector=>selector.includes('.block-hover') ? {} : null};
    translation.onMove({target:button,buttons:0});c.tick(200);assert.equal(hidden,false);
  }finally{c.restore();}
});

test('turning automatic translation off keeps opening a paper local',async()=>{
  const c=Object.create(TranslationController.prototype);
  c.reader={id:'paper',alive:true,current:1,tmode:'side',pages:[],nav:{refreshSections(){}}};
  c.app={settings:{data:{provider:'demo',auto_translate:false},active:()=>({available:true})},api:{get:async()=>({language:'Korean',blocks:{}})}};
  c.pollJobs=async()=>{c.jobs=[];return true;};c.enqueue=()=>assert.fail('auto translation is disabled');
  await c.onAnalysis();
});

for (const [name,top,height,delta,mode,expected] of [
  ['no overflow',0,100,40,0,40], ['inside',50,300,40,0,null],
  ['bottom',200,300,40,0,40], ['top',0,300,-40,0,-40],
  ['back into content',200,300,-40,0,null], ['line units',200,300,2,1,32],
  ['page units',200,300,1,2,100]
]) test('translation wheel chains to PDF: '+name,()=>{
  const c=Object.create(TranslationController.prototype);let scrolled=null,prevented=false;
  c.reader={pagesEl:{scrollBy(x,y){scrolled=y;}}};
  const column={scrollTop:top,scrollHeight:height,clientHeight:100};
  c.onCardWheel({target:{closest:()=>column},deltaY:delta,deltaX:0,deltaMode:mode,preventDefault(){prevented=true;}});
  assert.equal(scrolled,expected);assert.equal(prevented,expected!==null);
});
test('pinch zoom and horizontal gestures keep their default behavior',()=>{
  const c=Object.create(TranslationController.prototype);c.reader={pagesEl:{scrollBy(){assert.fail('unrelated gesture');}}};
  for(const extras of [{ctrlKey:true},{deltaX:100},{defaultPrevented:true}]) c.onCardWheel({
    target:{closest:()=>({scrollTop:0,scrollHeight:100,clientHeight:100})},deltaY:10,deltaX:0,...extras,
    preventDefault(){assert.fail('unrelated gesture');}
  });
});
test('chat sends the selected model with its question',async()=>{
  const c=Object.create(AssistantPanel.prototype);let sent;
  c.reader={title:()=> 'Paper'};c.history={ready:Promise.resolve(true),turns:[]};c.modelChoices={qa:'large'};
  c.app={settings:{active:()=>({id:'qa'})},api:{post:async(path,body)=>{sent=body;return {text:'answer',provider_id:'qa',model:body.model};}}};
  c.renderHead=c.renderThread=()=>{};c.saveTurns=async()=>{};c.providerLabel=id=>id;c.tab='chat';
  await c.run({task:'ask',text:'Paper body',question:'Why?'});
  assert.equal(sent.model,'large');assert.equal(c.history.turns[0].model,'large');
});

test('highlight hit testing respects the page and rectangle',()=>{
  const annotations=Object.create(Annotations.prototype);
  annotations.items=[{id:'a',page:1,rects:[[.1,.2,.3,.4]]},{id:'other',page:2,rects:[[.1,.2,.3,.4]]}];
  const page={dataset:{page:'1'},getBoundingClientRect:()=>({left:0,top:0,width:100,height:100})};
  assert.equal(annotations.annotationAt(page,20,30).id,'a');assert.equal(annotations.annotationAt(page,70,30),undefined);
});
test('floating note protects IME composition and saves through command Enter',async()=>{
  const annotations=Object.create(Annotations.prototype);
  const result=annotations.noteDialog('Note','','Quote');const area=annotations.editor.area;
  for(const data of [{key:'Enter',metaKey:true,isComposing:true},{key:'Escape',keyCode:229}]) {
    area.listeners.keydown({...data,preventDefault(){assert.fail('composition cancelled');},stopPropagation(){}});
    assert.ok(annotations.editor);
  }
  area.value='  My note  ';
  area.listeners.keydown({key:'Enter',metaKey:true,preventDefault(){},stopPropagation(){}});
  assert.equal(await result,'My note');assert.equal(annotations.editor,null);
});
test('floating note moves within the viewport and keeps an existing draft',async()=>{
  const annotations=Object.create(Annotations.prototype);
  const result=annotations.noteDialog('Note','Draft','Quote');
  const area=annotations.editor.area;
  assert.equal(await annotations.noteDialog('Second note','',''),null);assert.equal(annotations.editor.area,area);
  const panel=document.body.children.at(-1),header=panel.children[0];
  header.listeners.pointerdown({button:0,target:{closest:()=>null},clientX:110,clientY:120,pointerId:1,preventDefault(){}});
  header.listeners.pointermove({clientX:1000,clientY:1000});
  assert.equal(panel.style.left,'392px');assert.equal(panel.style.top,'212px');
  annotations.editor.close(null);assert.equal(await result,null);
});

test('a same-page reference pulses the original without loading an image',()=>{
  const visual=Object.create(Visuals.prototype);let flashed;
  visual.reader={flashRect(...args){flashed=args;},cropImage(){assert.fail('same-page image');}};
  const target={page:2,rect:[.1,.2,.8,.5]};
  assert.equal(visual.previewContent(target,2),null);assert.deepEqual(flashed,[2,target.rect,false,true]);
});
test('the same note toggles visibility without discarding its draft',async()=>{
  const annotations=Object.create(Annotations.prototype);annotations.reader={pages:[]};
  const note={id:'saved-note',page:1,note:'Saved',text:'Quote',rects:[[.1,.2,.3,.4]]};
  const first=annotations.editNote(note,{left:20,right:80,top:30});
  annotations.editor.area.value='Unsaved draft';
  assert.equal(annotations.editor.panel.style.left,'92px');assert.equal(annotations.editor.panel.style.top,'30px');
  await annotations.editNote(note);assert.equal(annotations.editor.panel.hidden,true);
  await annotations.editNote(note);assert.equal(annotations.editor.panel.hidden,false);
  assert.equal(annotations.editor.area.value,'Unsaved draft');
  annotations.editor.close(null);await first;
});

function titlePdf(metadataTitle) {
  function item(str,top,size,width=480) { return {str,height:size,width,transform:[size,0,0,size,60,800-top]}; }
  return {
    getMetadata:async()=>({info:{Title:metadataTitle}}),
    getPage:async()=>({view:[0,0,600,800],getViewport:()=>({width:600,height:800}),getTextContent:async()=>({items:[
      item('A Reliable Reader for Scientific Papers',100,22),
      item('Abstract',170,12),
      item('This paragraph establishes the normal font size for this document.',200,10),
      item('The following sentence contains enough text for a stable estimate.',214,10),
      item('A further line of body text makes the title visually distinct.',228,10)
    ]})})
  };
}
test('import uses valid PDF metadata and falls back to the first-page title',async()=>{
  assert.equal(await extractPdfTitle(titlePdf('Metadata Paper Title'),'1234.pdf'),'Metadata Paper Title');
  for (const value of ['', 'Untitled', 'neurips_2026', 'Microsoft Word - main.docx','2601.12345'])
    assert.equal(await extractPdfTitle(titlePdf(value),'neurips_2026.pdf'),'A Reliable Reader for Scientific Papers');
});
test('import preserves long multi-line paper titles up to 300 characters',async()=>{
  const title='A comprehensive account of scientific reading and reproducibility across heterogeneous datasets, model families, and independently trained experimental systems';
  assert.equal(await extractPdfTitle(titlePdf(title),'file.pdf'),title);
});

function translationPage() {
  function container() { return {children:[],scrollTop:145,style:{},
    replaceChildren(){this.children=[];},
    insertBefore(node,before){const old=this.children.indexOf(node);if(old>=0)this.children.splice(old,1);const at=this.children.indexOf(before);this.children.splice(at<0?this.children.length:at,0,node);node.parentNode=this;},
    append(node){this.insertBefore(node,null);}}; }
  const over=container(), tcol=container();
  const state={number:1,rendered:true,el:{offsetHeight:800,offsetWidth:600,querySelector:()=>over,querySelectorAll:()=>[]},tcol};
  const blocks=['first','second'].map((key,i)=>({key,page:1,kind:'body',translatable:true,rect:[0,.1+i*.2,1,.2+i*.2],parts:[{page:1}],sentences:['Source.']}));
  const c=Object.create(TranslationController.prototype);
  c.reader={alive:true,tmode:'side',pages:[state],analysis:{pages:[{blocks}],blocks}};
  c.store={first:{sentences:['Translation.']},second:{sentences:['Other.']}};c.pending=new Set();
  c.card=block=>({dataset:{key:block.key},style:{},offsetHeight:80,entry:JSON.stringify(c.store[block.key]||null),
    remove(){this.parentNode.children.splice(this.parentNode.children.indexOf(this),1);}});
  return {c,state,blocks};
}
test('polling keeps hovered translation nodes, selection and scroll intact',()=>{
  const {c,state}=translationPage();c.renderPage(state);
  const card=state.tcol.children[0];card.hovered=true;card.selected=true;
  c.renderPage(state);
  assert.equal(state.tcol.children[0],card);assert.equal(card.hovered,true);assert.equal(card.selected,true);assert.equal(state.tcol.scrollTop,145);
  c.store.second={sentences:['Updated other paragraph.']};c.renderPage(state);
  assert.equal(state.tcol.children[0],card);assert.notEqual(state.tcol.children[1].entry,JSON.stringify({sentences:['Other.']}));
});
test('translation status distinguishes preparing, first response, progress and interruption',()=>{
  const c=Object.create(TranslationController.prototype);
  c.reader={tmode:'side',analysis:{blocks:[]}};c.app={settings:{data:{auto_translate:true,provider:'qa'}}};
  c.label={};c.button={classList:{toggle(){}}};c.status={classList:{toggle(){}}};c.statusText={};c.progress={};
  c.store={};c.jobs=[];c.submitting=new Set(['first']);c.updateLabel();
  assert.match(c.statusText.textContent,/준비/);
  c.submitting.clear();c.running=true;c.done=0;c.total=12;c.updateLabel();
  assert.match(c.statusText.textContent,/0\/12/);assert.match(c.statusText.textContent,/응답/);assert.equal(c.progress.value,0);
  c.done=10;c.updateLabel();assert.match(c.statusText.textContent,/10\/12/);assert.equal(c.progress.value,10);
  c.running=false;c.jobs=[{state:'failed'}];c.updateLabel();assert.match(c.statusText.textContent,/중단/);
});
test('active jobs restore pending paragraphs after reopening and clear them when stopped',async()=>{
  const c=Object.create(TranslationController.prototype);let state='running';
  c.reader={id:'paper',alive:true,pages:[],nav:{refreshSections(){}}};c.language='Korean';c.submitting=new Set();c.pending=new Set();
  c.app={api:{get:async path=>path.endsWith('translation-jobs') ? {jobs:[{state,language:'Korean',completed:0,total:2,pending_keys:['first','second']}]} : {blocks:{first:{text:'Saved.'}}}}};
  c.updateLabel=()=>{};
  try {await c.pollJobs();assert.deepEqual([...c.pending],['second']);state='failed';await c.pollJobs();assert.deepEqual([...c.pending],[]);}
  finally{clearTimeout(c.pollTimer);}
});

test('same paragraph keeps its sentence highlight over word spaces and line gaps',()=>{
  const c=Object.create(TranslationController.prototype), block={sentences:['First sentence.','Second sentence.']};
  const state={map:{blockRects:(b,start)=>start===0 ? [[.1,.1,.4,.12]] : [[.1,.15,.4,.17]]}};
  for(let x=.1;x<.4;x+=.003) assert.equal(c.sentenceAt(state,block,-1,x,.13),0);
  assert.equal(c.sentenceAt(state,block,-1,.2,.145),1);
  assert.equal(c.sentenceAt(state,block,0,.2,.16),0);
});
test('moving through whitespace in one translated card does not clear its highlight',()=>{
  const c=Object.create(TranslationController.prototype);let cleared=0;
  c.clearSentence=()=>cleared++;const gap={},card={contains:node=>node===gap},span={closest:()=>card};
  c.onCardOut({target:{closest:selector=>selector==='.tsent'?span:null},relatedTarget:gap});assert.equal(cleared,0);
  c.onCardOut({target:{closest:selector=>selector==='.tsent'?span:null},relatedTarget:{}});assert.equal(cleared,1);
});
test('Docling paragraph boxes retain left-column then right-column reading order',()=>{
  const pages=[{width:600,height:800,items:[]}];
  const raw={pages:[{number:1,width:600,height:800,blocks:[
    {ref:'right',text:'Right column paragraph.',kind:'paragraph',rect:[.55,.1,.9,.2],captions:[]},
    {ref:'left-bottom',text:'Left column second paragraph.',kind:'paragraph',rect:[.1,.3,.45,.4],captions:[]},
    {ref:'left-top',text:'Left column first paragraph.',kind:'paragraph',rect:[.1,.1,.45,.2],captions:[]}
  ]}]};
  const result=analyzeDocling(pages,raw);
  assert.deepEqual(result.blocks.map(b=>b.sourceRef),['left-top','left-bottom','right']);assert.ok(result.blocks.every(b=>b.translatable));
});
test('semantic text matching cannot jump to identical text in a different column',()=>{
  const map=Object.create(TextMap.prototype);map.page=1;map.blockCache=new Map();
  map.el={getBoundingClientRect:()=>({left:0,top:0,width:100,height:100})};
  const text='Identical sentence.';map.compact=text.replaceAll(' ','').repeat(2);const len=map.compact.length/2;
  map.nodeStart=[0,len];map.nodes=[10,60].map(x=>({data:text,parentElement:{getBoundingClientRect:()=>({left:x,right:x+20,top:10,bottom:20})}}));
  const parts=map.locateBlock({semantic:true,key:'right',text,parts:[{page:1,rect:[.55,.05,.9,.25]}]});
  assert.equal(parts[0].pageStart,len);
});
test('translation card order follows analysis order across two columns',()=>{
  const {c,state,blocks}=translationPage();blocks[0].rect=[.1,.5,.45,.6];blocks[1].rect=[.55,.1,.9,.2];
  c.renderPage(state);assert.deepEqual(state.tcol.children.map(n=>n.dataset.key),['first','second']);
});

test('an offscreen linked sentence scrolls only its translation column smoothly',()=>{
  const c=Object.create(TranslationController.prototype);let scroll;
  c.reader={pagesEl:{getBoundingClientRect:()=>({top:100,bottom:600}),scrollBy(){assert.fail('PDF must remain in place');}}};
  const column={getBoundingClientRect:()=>({top:80,bottom:680}),scrollBy:options=>scroll=options};
  const span={closest:()=>column,getClientRects:()=>[{top:900,bottom:920}]};
  c.revealTranslation(span);assert.equal(scroll.behavior,'smooth');assert.ok(scroll.top>0);
  scroll=null;span.getClientRects=()=>[{top:200,bottom:220}];c.revealTranslation(span);assert.equal(scroll,null);
});
test('library progress shows analysis, active translation, interruption and automatic start',()=>{
  const c=Object.create(LibraryView.prototype);c.app={settings:{data:{auto_translate:true}}};
  c.activity={analysis:[{doc_id:'paper',state:'preparing'}],translations:[]};assert.match(c.progressText('paper'),/모델 준비/);
  c.activity.analysis=[];c.activity.translations=[{doc_id:'paper',state:'running',completed:3,total:12}];assert.match(c.progressText('paper'),/3\/12/);
  c.activity.translations[0].state='failed';assert.match(c.progressText('paper'),/중단.*3\/12/);
  c.activity.translations=[];assert.match(c.progressText('paper'),/자동 번역/);
});

test('a PDF drop is handled once instead of bubbling into a second upload',()=>{
  const c=Object.create(LibraryView.prototype);let imports=0,stopped=false;
  c.route={scope:'all'};c.app={importFiles:()=>imports++};const body=new Element();
  c.attachFileDrop(body);
  body.listeners.drop({dataTransfer:{types:['Files'],files:[{name:'paper.pdf',type:'application/pdf'}]},preventDefault(){},stopPropagation(){stopped=true;}});
  assert.equal(imports,1);assert.equal(stopped,true);
});
test('inline math highlights as one box per line at the body text height',async()=>{
  const { lineRects }=await import('../../src/paperdesk/web/static/js/textmap.js');
  const rects=[[.10,.100,.30,.120],[.31,.098,.33,.121],[.33,.110,.34,.123],[.35,.100,.40,.120],[.41,.092,.44,.128],[.44,.115,.48,.127],[.10,.125,.20,.145]];
  assert.deepEqual(lineRects(rects),[[.10,.100,.48,.120],[.10,.125,.20,.145]]);
  assert.deepEqual(lineRects([[.1,.1,.2,.12],[.6,.1,.7,.12]]),[[.1,.1,.2,.12],[.6,.1,.7,.12]]);
});
test('the translation menu offers only what fits the current state',()=>{
  const c=Object.create(TranslationController.prototype);
  const blocks=[1,2,3].map(n=>({key:'1:'+n,translatable:true}));
  Object.assign(c,{reader:{tmode:'side',current:1,analysis:{blocks,pages:[{blocks}]}},language:'Korean',store:{},pending:new Set(),jobs:[],running:false});
  const labels=()=>c.menuItems().filter(item=>item!=='-').map(item=>item.label||item.title).slice(4);
  assert.deepEqual(labels(),['현재 쪽 번역','목차에서 골라 번역…','남은 본문 전체 번역 (3문단)']);
  // Running a job for the whole paper: nothing to start again, nothing to redo; only stopping.
  c.running=true;c.pending=new Set(blocks.map(b=>b.key));c.store={'1:1':{}};c.pending.delete('1:1');
  c.jobs=[{language:'Korean',state:'running',completed:1,total:3}];
  assert.deepEqual(labels(),['번역 멈추기']);
  // Interrupted: resume or cancel it, or start over on what is left.
  c.running=false;c.pending=new Set();c.jobs=[{id:'j',language:'Korean',state:'paused',completed:1,total:3}];
  assert.deepEqual(labels(),['중단된 번역 재개 (1/3)','중단 작업 취소','현재 쪽 번역','목차에서 골라 번역…','새 분석으로 남은 본문 번역…','현재 쪽 다시 번역…']);
  // Everything translated.
  c.jobs=[{language:'Korean',state:'completed',completed:3,total:3}];c.store={'1:1':{},'1:2':{},'1:3':{}};
  assert.deepEqual(labels(),['전체 번역 완료','현재 쪽 다시 번역…']);
});
test('library rows show the first author, year and venue once details are found',()=>{
  assert.equal(paperDetails({authors:'Ashish Vaswani, Noam Shazeer',year:'2017',venue:'Neural Information Processing Systems'}),
    'Vaswani 외 · 2017 · Neural Information Processing Systems');
  assert.equal(paperDetails({authors:'Kaiming He',year:'2016',venue:''}),'He · 2016');
  assert.equal(paperDetails({authors:'',year:'',venue:''}),'');
  const view=Object.create(LibraryView.prototype);view.app={};
  const labels=ids=>{view.selected=new Set(ids);return view.documentMenu({id:'a'}).filter(i=>i!=='-').map(i=>i.label||i.title);};
  assert.ok(labels(['a']).includes('BibTeX 복사')&&labels(['a']).includes('논문 정보 다시 찾기'));
  assert.ok(labels(['a','b']).includes('BibTeX 2편 복사')&&!labels(['a','b']).includes('논문 정보 다시 찾기'));
});
test('imports are prepared one at a time and only those with pages to translate are translated',async()=>{
  const background=new BackgroundImport({}), seen=[];
  background.prepare=async(id,organize)=>{seen.push(id+(organize?':organize':''));return id==='b'?{texts:[]}:null;};
  background.translate=async id=>{seen.push(id+':translate');};
  background.add(['a','b'],true);background.add(['c'],false);
  await background.queue;await background.translations;
  assert.deepEqual(seen.filter(s=>!s.endsWith(':translate')),['a:organize','b:organize','c']);
  assert.deepEqual(seen.filter(s=>s.endsWith(':translate')),['b:translate']);
});
