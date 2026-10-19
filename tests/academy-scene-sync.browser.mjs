import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {chromium} from '../frontend/node_modules/playwright/index.mjs';
const production=process.env.ACADEMY_PRODUCTION;
assert.ok(production,'Set ACADEMY_PRODUCTION to the source-bound production directory.');
const base=(process.env.BASE_URL||'http://127.0.0.1:8794/learn/').replace(/\/?$/,'/');
const read=file=>JSON.parse(fs.readFileSync(path.join(production,file),'utf8'));
const partial=process.env.QA_PARTIAL==='1';
const selected=(process.env.QA_VIDEOS||'').split(',').filter(Boolean);
assert.ok(!selected.length||partial,'QA_VIDEOS requires QA_PARTIAL=1; a filtered run cannot verify all29 videos.');
const index=read('video-index.json');const groupPath=path.join(production,'video-groups.json');
const groups=fs.existsSync(groupPath)?read('video-groups.json').groups:partial?[]:read('video-groups.json').groups;
const browser=await chromium.launch({channel:process.env.BROWSER_CHANNEL||'msedge',headless:true});
const page=await browser.newPage();page.setDefaultTimeout(60000);
page.on('pageerror',error=>console.error('BROWSER ERROR '+error.message));
await page.route('**/__academy_qa_video.html',route=>route.fulfill({status:200,contentType:'text/html',body:'<!doctype html><html><body><video muted preload="auto"></video></body></html>'}));
const results=[];
const imageURL=file=>'data:image/png;base64,'+fs.readFileSync(file).toString('base64');
async function compare(video, row, offset=0, relative=1, expectedFile=row.picture,motion=null){
 const rawTime=offset+row.start+Math.min(relative,(row.end-row.start)-.05);
 const at=(Math.floor(rawTime*24+1e-5)+.5)/24;
 console.log(`CHECK ${row.lesson}/${row.id} at ${at.toFixed(3)}s`);
 let nodeTimer;
 const actual=await Promise.race([video.evaluate(async(v,{at,url,motion})=>{
  let presentedTime;
  const expected=new Image();expected.src=url;await Promise.race([expected.decode(),new Promise((_,reject)=>setTimeout(()=>reject(Error('Expected PNG did not decode')),10000))]);
  let endpoints;
  if(motion){
   endpoints=await Promise.all([motion.before,motion.after].map(async src=>{const img=new Image();img.src=src;await img.decode();return img;}));
  }
  await new Promise((resolve,reject)=>{
   const timer=setTimeout(()=>reject(Error('No decoded frame presented after seek')),30000);
   const finish=()=>{v.pause();clearTimeout(timer);resolve();};
   if(!v.requestVideoFrameCallback){reject(Error('This browser cannot verify presented video frames'));return;}
   {
    const presented=(now,meta)=>{if(Math.abs(meta.mediaTime-(Math.floor(at*24)/24))<.001){presentedTime=meta.mediaTime;finish();}else v.requestVideoFrameCallback(presented);};
    v.requestVideoFrameCallback(presented);
   }
   v.addEventListener('error',()=>{clearTimeout(timer);reject(Error('Decode failed'));},{once:true});v.currentTime=at;
   v.play().catch(reject);
  });
  if(v.seeking)await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('Seek did not settle')),10000);v.addEventListener('seeked',()=>{clearTimeout(timer);resolve();},{once:true});});
  if(v.readyState<2)throw Error('Presented frame has no decoded data');
  const a=document.createElement('canvas'),b=document.createElement('canvas');a.width=b.width=854;a.height=b.height=480;
  const ac=a.getContext('2d',{willReadFrequently:true}),bc=b.getContext('2d',{willReadFrequently:true});ac.drawImage(v,0,0,854,480);bc.drawImage(expected,0,0,854,480);
  const x=ac.getImageData(0,0,854,480).data,y=bc.getImageData(0,0,854,480).data;let total=0,n=0,large=0;
  for(let py=0;py<480;py+=3)for(let px=0;px<854;px+=3){const i=(py*854+px)*4;for(let c=0;c<3;c++){const d=Math.abs(x[i+c]-y[i+c]);total+=d;n++;if(d>30)large++;}}
  let movement;
  if(endpoints){
   const pixels=endpoints.map(img=>{bc.clearRect(0,0,854,480);bc.drawImage(img,0,0,854,480);return bc.getImageData(0,0,854,480).data;});
   let matched=0,opposite=0,channels=0;
   for(let i=0;i<x.length;i+=4){
    if(Math.max(...[0,1,2].map(c=>Math.abs(pixels[0][i+c]-pixels[1][i+c])))<=25)continue;
    for(let c=0;c<3;c++){matched+=Math.abs(x[i+c]-pixels[motion.endpoint][i+c]);opposite+=Math.abs(x[i+c]-pixels[1-motion.endpoint][i+c]);channels++;}
   }
   movement={changedPixels:channels/3,matchedError:matched/channels,oppositeError:opposite/channels};
  }
  return {at:v.currentTime,presentedTime,meanAbsoluteError:total/n,largeDifferenceFraction:large/n,...(movement?{movement}: {})};
 },{at,url:imageURL(expectedFile),motion:motion?{before:imageURL(motion.before),after:imageURL(motion.after),endpoint:motion.endpoint}:null}),new Promise((_,reject)=>{nodeTimer=setTimeout(()=>reject(Error(`Scene comparison timed out: ${row.lesson}/${row.id} at ${at}`)),45000);})]).finally(()=>clearTimeout(nodeTimer));
 assert.ok(Math.abs(actual.at-at)<.12,`Actual seek ${actual.at} differs from ${at}`);
 assert.ok(actual.meanAbsoluteError<7&&actual.largeDifferenceFraction<.08,`${row.lesson}/${row.id} picture does not match voice-bound scene at ${at}: ${JSON.stringify(actual)}`);
 if(motion)assert.ok(actual.movement.changedPixels>0&&actual.movement.matchedError<20&&actual.movement.matchedError<actual.movement.oppositeError,`Threshold movement endpoint does not match its changed pixels: ${JSON.stringify(actual.movement)}`);
 return actual;
}
try{
 const entries=[...Object.entries(index.lessons).map(([id,v])=>({id,kind:'lesson',src:v.src,lessons:[id]})),...groups.map(g=>({id:g.id,kind:'group',src:g.src,lessons:g.lessons}))].filter(entry=>!selected.length||selected.includes(entry.id));
 assert.ok(entries.length,'No completed videos selected.');
 for(const id of selected)assert.ok(entries.some(entry=>entry.id===id),'Selected video is not complete: '+id);
 for(const entry of entries){
  console.log(`LOAD ${entry.kind} ${entry.id}: ${new URL(entry.src,base).href}`);
  await page.goto(new URL('__academy_qa_video.html',base).href,{waitUntil:'domcontentloaded'});
  const video=page.locator('video');
  await video.evaluate((v,src)=>{v.src=src;v.load();},new URL(entry.src,base).href);
  await page.waitForFunction(()=>document.querySelector('video')?.readyState>=2);
  console.log(`DECODE READY ${entry.id}`);
  let offset=0,count=0,max=0;
  for(const lid of entry.lessons){
   const rows=read('reports/'+lid+'-timeline.json');
   for(const row of rows){
    if(row.id==='B1-05-p03'){
     const ready=read('motion/B1-05-p03/ready.json');
     const endpoints=[24,ready.frames-24];
     const motionFile=frame=>path.join(production,'motion/B1-05-p03/frames/frame_'+String(frame).padStart(4,'0')+'.png');
     for(const frame of [endpoints[0],Math.round((ready.movement_start_frame+ready.movement_end_frame)/2),endpoints[1]]){
      const file=path.join(production,'motion/B1-05-p03/frames/frame_'+String(frame).padStart(4,'0')+'.png');
      const motion=endpoints.includes(frame)?{before:motionFile(endpoints[0]),after:motionFile(endpoints[1]),endpoint:endpoints.indexOf(frame)}:null;
      const actual=await compare(video,row,offset,(frame+.5)/24,file,motion);max=Math.max(max,actual.meanAbsoluteError);count++;results.push({video:entry.id,kind:entry.kind,scene:row.id,frame,...actual});
     }
    }else{const actual=await compare(video,row,offset,1);max=Math.max(max,actual.meanAbsoluteError);count++;results.push({video:entry.id,kind:entry.kind,scene:row.id,...actual});}
   }
   offset+=rows.at(-1).end;
  }
  fs.mkdirSync(path.join(production,'scene-sync-qa'),{recursive:true});fs.writeFileSync(path.join(production,'scene-sync-qa/'+(partial?'results-partial.json':'results.json')),JSON.stringify(results,null,2)+'\n');
  console.log(`PASS ${entry.kind} ${entry.id}: ${count} decoded scene comparisons, max MAE ${max.toFixed(3)}`);
 }
 if(!partial)assert.equal(entries.length,29);
 console.log(partial?'PASS partial validation of '+entries.length+' completed videos; full29 validation remains pending.':'PASS all29 actual videos match their voice-bound scene images, including the timed threshold movement.');
}catch(error){console.error(error);process.exitCode=1;}finally{
 let closeTimer;
 try{await Promise.race([browser.close(),new Promise(()=>{closeTimer=setTimeout(()=>{console.error('Browser shutdown timed out');process.exit(1);},5000);})]);}
 finally{clearTimeout(closeTimer);}
}
