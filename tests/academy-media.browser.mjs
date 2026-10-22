import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {chromium} from '../frontend/node_modules/playwright/index.mjs';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const base=(process.env.BASE_URL || 'http://127.0.0.1:8794/learn/').replace(/\/?$/,'/');
const out=path.resolve(process.env.ACADEMY_QA_DIR || path.join(root,'output/playwright/academy-media'));
fs.mkdirSync(out,{recursive:true});
const sha=data=>crypto.createHash('sha256').update(data).digest('hex');
const browser=await chromium.launch({channel:process.env.BROWSER_CHANNEL || 'msedge',headless:true,args:['--disable-gpu']});
const page=await browser.newPage({viewport:{width:1280,height:1000}});
page.setDefaultTimeout(60000);
const errors=[];page.on('pageerror',e=>errors.push(e.message));
const results={base,edition:'2026-10-20-r4',videos:[]};
try{
 const course=await (await page.request.get(base+'course/course.json?verify=r3')).json();
 const manifest=await (await page.request.get(base+'media/manifest.json?verify=r3')).json();
 const grouped=await (await page.request.get(base+'course/video-groups.json?verify=r3')).json();
 assert.equal(course.edition,results.edition);assert.equal(manifest.edition,course.edition);assert.equal(grouped.edition,course.edition);
 assert.equal(course.lessons.length,24);assert.ok(course.lessons.every(l=>l.video?.src));assert.equal(grouped.groups.length,5);
 const entries=[...course.lessons.map(l=>({id:l.id,kind:'lesson',route:'lesson/'+l.id,video:l.video})),...grouped.groups.map(g=>({id:g.id,kind:'group',route:'watch/'+g.id,video:g}))];
 for(const entry of entries){
  const metadata=entry.video;assert.match(metadata.src,/v=20261020r4/);
  await page.goto(base+'?verify=r3#/'+entry.route,{waitUntil:'domcontentloaded',timeout:90000});
  const video=page.locator('video');await video.waitFor();
  await page.waitForFunction(()=>document.querySelector('video')?.readyState>=1);
  const played=await video.evaluate(async v=>{v.muted=true;await v.play();for(let i=0;i<50&&v.currentTime<=.1;i++)await new Promise(r=>setTimeout(r,100));v.pause();return {duration:v.duration,time:v.currentTime,width:v.videoWidth,height:v.videoHeight,src:v.currentSrc};});
  assert.equal(played.src,new URL(metadata.src,base).href,'The requested lesson or group must be the video that actually loaded');
  assert.ok(played.time>.1,entry.id+' playback did not advance');assert.equal(played.width,854);assert.equal(played.height,480);assert.ok(Number.isFinite(played.duration)&&played.duration>30);
  await page.waitForFunction(()=>document.querySelector('video track')?.readyState===2);
  const cues=await video.evaluate(v=>Array.from(v.textTracks[0].cues).map(c=>({start:c.startTime,end:c.endTime,text:c.text})));
  assert.ok(cues.length>10);
  const lessonIds=entry.kind==='lesson'?[entry.id]:metadata.lessons;
  const expectedText=lessonIds.flatMap(id=>course.lessons.find(l=>l.id===id).slides.map(slide=>slide.narration)).join(' ').replace(/\s+/g,' ').trim();
  assert.equal(cues.filter(c=>c.text.replace(/\s+/g,' ').trim()!=='[Pause and answer before continuing.]').map(c=>c.text).join(' ').replace(/\s+/g,' ').trim(),expectedText,'All source words must remain in their matching video captions');assert.ok(cues.every(c=>c.end>c.start&&c.end<=played.duration+.1));
  const samples=[Math.min(played.duration-1,(metadata.chapters[1]?.start || played.duration*.25)+.2),played.duration*.65];
  for(const time of samples){
   await video.evaluate((v,t)=>{v.currentTime=t;},time);
   await page.waitForFunction(t=>{const v=document.querySelector('video');return v.readyState>=2&&!v.seeking&&Math.abs(v.currentTime-t)<.2;},time);
  }
  const captionSelector=entry.kind==='lesson'?'.lp-caption':'.group-captions';
  assert.equal(await page.locator(captionSelector).count(),1);
  await video.screenshot({path:path.join(out,entry.kind+'-'+entry.id+'.png')});
  const mediaPath=metadata.src.split('?')[0].replace(/^media\//,'');const expected=manifest.files.find(f=>f.path===mediaPath);assert.ok(expected,mediaPath+' missing from inventory');
  let actualHash;
  if(process.env.HASH_MEDIA==='1'){
   const response=await page.request.get(new URL(metadata.src,base).href,{timeout:180000});assert.equal(response.status(),200);const bytes=await response.body();assert.equal(bytes.length,expected.bytes);actualHash=sha(bytes);assert.equal(actualHash,expected.sha256);
  }
  results.videos.push({id:entry.id,kind:entry.kind,...played,captionCues:cues.length,samples,sha256:actualHash||expected.sha256,hashDownloaded:!!actualHash});
  fs.writeFileSync(path.join(out,'verification.json'),JSON.stringify(results,null,2)+'\n');
  console.log('PASS '+entry.kind+' '+entry.id+' '+played.duration.toFixed(2)+'s '+cues.length+' captions');
 }
 const response=await page.request.get(new URL('../dashboard.html',base).href);
 assert.equal(response.status(),200);
 const served=await response.body();
 results.dashboardHTTP_SHA256=sha(served);
 const stable=process.env.DASHBOARD_SHA256||sha(fs.readFileSync(path.join(root,'www/dashboard.html')));
 assert.equal(results.dashboardHTTP_SHA256,stable,'Serve the compiled www directory with Vite preview; actual app bytes must match the compiled www/dashboard.html (or DASHBOARD_SHA256)');
 results.dashboardServedBytesVerified=true;
 results.dashboardPublishedBytesVerified=base.startsWith('https:');
 assert.deepEqual(errors,[]);results.errors=errors;results.complete=true;
 fs.writeFileSync(path.join(out,'verification.json'),JSON.stringify(results,null,2)+'\n');
 console.log('PASS all24 individual and5group videos: captions, playback, real seeking and exact stable served app bytes.');
}finally{await browser.close();}
