// Deterministic teaching cards. No application server, external fonts or assets required.
export const PILOT_WIDTH = 854;
export const PILOT_HEIGHT = 480;
const NS = 'http://www.w3.org/2000/svg';
const C = { ink:'#17342c', muted:'#53645e', blue:'#1878b9', water:'#81c9ee', brown:'#a57b50', green:'#387557', orange:'#b76628', line:'#c7d6cf', pale:'#edf4ef', white:'#ffffff' };
function s(tag, attrs={}, text) { const n=document.createElementNS(NS,tag); for(const [k,v] of Object.entries(attrs))n.setAttribute(k,String(v)); if(text!==undefined)n.textContent=String(text); return n; }
function add(p,tag,attrs,text){const n=s(tag,attrs,text);p.append(n);return n;}
function text(p,x,y,value,size=22,fill=C.ink,anchor='start',weight=500){return add(p,'text',{x,y,'font-size':size,fill,'text-anchor':anchor,'font-weight':weight},value);}
function box(p,x,y,w,h,fill=C.white,stroke=C.line,rx=14){return add(p,'rect',{x,y,width:w,height:h,rx,fill,stroke,'stroke-width':2});}
function line(p,x1,y1,x2,y2,color=C.ink,width=3,dash){return add(p,'line',{x1,y1,x2,y2,stroke:color,'stroke-width':width,...(dash?{'stroke-dasharray':dash}:{})});}
function arrow(p,x1,y1,x2,y2,color=C.blue){line(p,x1,y1,x2,y2,color,4);const a=Math.atan2(y2-y1,x2-x1),d=10;add(p,'path',{d:`M ${x2-d*Math.cos(a-.5)} ${y2-d*Math.sin(a-.5)} L ${x2} ${y2} L ${x2-d*Math.cos(a+.5)} ${y2-d*Math.sin(a+.5)}`,fill:'none',stroke:color,'stroke-width':4});}
function wrap(value,max=25){const words=String(value).split(/\s+/),out=[];let row='';for(const w of words){if(row&&row.length+w.length+1>max){out.push(row);row=w;}else row+=(row?' ':'')+w;}if(row)out.push(row);return out;}
function lines(p,x,y,value,max=25,size=22,fill=C.ink,anchor='start',gap=29){wrap(value,max).forEach((r,i)=>text(p,x,y+i*gap,r,size,fill,anchor));}
function tag(p,x,y,value,color=C.green){box(p,x,y,210,43,C.white,color,10);text(p,x+105,y+28,value,21,color,'middle',650);}
function labelStack(p,labels,x=350,y=65,w=400){labels.forEach((v,i)=>{box(p,x,y+i*76,w,64,C.white,C.line,11);lines(p,x+18,y+27+i*76,v,Math.floor((w-30)/11.4),22);});}
function pot(p,x=65,y=75,w=190,h=185,{wet=false,probe=false,air=true}={}){
 add(p,'path',{d:`M ${x} ${y} L ${x+18} ${y+h} L ${x+w-18} ${y+h} L ${x+w} ${y} Z`,fill:wet?'#a6d8f1':'#e4cdb2',stroke:C.ink,'stroke-width':3});
 const rocks=[[.13,.13,.18,.15],[.43,.08,.2,.18],[.75,.14,.13,.18],[.26,.4,.22,.15],[.65,.43,.22,.17],[.12,.68,.19,.17],[.45,.75,.22,.16],[.73,.72,.12,.15]];
 rocks.forEach(([a,b,c,d],i)=>add(p,'ellipse',{cx:x+(a+c/2)*w,cy:y+(b+d/2)*h,rx:c*w/2,ry:d*h/2,fill:C.brown,transform:`rotate(${i%2?20:-18} ${x+(a+c/2)*w} ${y+(b+d/2)*h})`}));
 [[.32,.22],[.64,.28],[.34,.66],[.8,.61]].forEach(([a,b],i)=>add(p,'ellipse',{cx:x+a*w,cy:y+b*h,rx:15,ry:10,fill:air&&i%2===0?C.white:C.water,stroke:air&&i%2===0?C.line:C.blue,'stroke-width':1.5}));
 add(p,'path',{d:`M ${x+w*.51} ${y+5} Q ${x+w*.45} ${y+70} ${x+w*.53} ${y+140} M ${x+w*.49} ${y+60} l -32 25 M ${x+w*.5} ${y+100} l 32 30`,stroke:'#6c4a2d','stroke-width':3,fill:'none'});
 if(probe){line(p,x+w*.78,y-26,x+w*.64,y+92,C.ink,9);add(p,'circle',{cx:x+w*.64,cy:y+92,r:30,fill:'none',stroke:C.orange,'stroke-width':3,'stroke-dasharray':'6 4'});}
}
function rootZone(p,v){pot(p,70,52,220,205,{wet:v.focus==='wet',air:v.focus!=='wet'});const labels=v.labels.length?v.labels:['Solid material','Water','Air'];labels.slice(0,3).forEach((l,i)=>{const y=82+i*73;box(p,398,y-29,365,62,C.white,C.line,12);add(p,'circle',{cx:424,cy:y-1,r:10,fill:[C.brown,C.water,C.white][i],stroke:[C.brown,C.blue,C.line][i],'stroke-width':2});lines(p,448,y+(String(l).length>26?-5:7),l,26,22,C.ink,'start',25);line(p,[188,246,145][i],[91,177,187][i],386,y,C.muted,2);});}
function drainage(p,v){pot(p,280,55,190,164,{wet:false});line(p,240,22,370,22,C.blue,7);arrow(p,370,22,370,50);lines(p,35,25,v.labels[0]||'Water enters',18,22,C.blue);arrow(p,367,224,367,252);box(p,260,260,230,27,'#b1dff5',C.blue,6);lines(p,532,108,v.labels[1]||'Some water stays',22,22);line(p,470,114,518,114,C.blue,2);lines(p,532,261,v.labels[2]||'Some drains to the tray',22,22);line(p,494,272,520,272,C.blue,2);}
function losses(p,v){pot(p,305,87,170,160);arrow(p,390,84,390,42,C.green);text(p,390,28,v.labels[0]||'Plant uptake',22,C.green,'middle');arrow(p,305,132,178,85,C.orange);lines(p,50,60,v.labels[1]||'Evaporation',18,22,C.orange);arrow(p,393,252,393,282,C.blue);text(p,495,283,v.labels[2]||'Drainage',22,C.blue);}
function panelIcon(p,cx,cy,kind,color=C.green){
 if(kind==='time'){add(p,'circle',{cx,cy,r:32,fill:'none',stroke:color,'stroke-width':4});line(p,cx,cy,cx,cy-22,color,4);line(p,cx,cy,cx+19,cy+11,color,4);}
 else if(kind==='water'){add(p,'path',{d:`M ${cx} ${cy-35} Q ${cx-47} ${cy+19} ${cx} ${cy+35} Q ${cx+47} ${cy+19} ${cx} ${cy-35}`,fill:C.water,stroke:C.blue,'stroke-width':3});}
 else if(kind==='sun'){add(p,'circle',{cx,cy,r:20,fill:'#edbd66',stroke:C.orange,'stroke-width':3});for(let a=0;a<8;a++){const t=a*Math.PI/4;line(p,cx+28*Math.cos(t),cy+28*Math.sin(t),cx+39*Math.cos(t),cy+39*Math.sin(t),C.orange,3);}}
 else if(kind==='temperature'){box(p,cx-8,cy-34,16,58,C.white,C.orange,8);add(p,'circle',{cx,cy:cy+25,r:16,fill:'#eabd78',stroke:C.orange,'stroke-width':3});line(p,cx,cy+21,cx,cy-20,C.orange,5);}
 else if(kind==='question'){add(p,'circle',{cx,cy,r:34,fill:C.pale,stroke:color,'stroke-width':3});text(p,cx,cy+15,'?',42,color,'middle',750);}
 else if(kind==='step'){add(p,'circle',{cx,cy,r:32,fill:C.pale,stroke:color,'stroke-width':3});arrow(p,cx-18,cy,cx+18,cy,color);}
 else if(kind==='plant'){line(p,cx,cy+30,cx,cy-22,color,4);add(p,'ellipse',{cx:cx-17,cy:cy-7,rx:21,ry:10,fill:'#8ab797',transform:`rotate(30 ${cx-17} ${cy-7})`});add(p,'ellipse',{cx:cx+17,cy:cy-22,rx:21,ry:10,fill:'#8ab797',transform:`rotate(-30 ${cx+17} ${cy-22})`});}
 else if(kind==='check'){add(p,'circle',{cx,cy,r:33,fill:C.pale,stroke:color,'stroke-width':3});add(p,'path',{d:`M ${cx-18} ${cy} l 13 14 l 25 -31`,fill:'none',stroke:color,'stroke-width':5});}
 else if(kind==='sensor'){line(p,cx-10,cy-30,cx+11,cy+28,color,9);add(p,'circle',{cx:cx+11,cy:cy+28,r:18,fill:'none',stroke:C.orange,'stroke-width':3});}
 else {box(p,cx-35,cy-29,70,53,C.white,color,6);line(p,cx-21,cy+32,cx+21,cy+32,color,3);}
}
function panels(p,v,icons=[]){const labels=v.labels.length?v.labels:['Observe','Check','Explain'];const n=labels.length,w=n===1?500:n===2?330:n===3?233:n===4?175:139,g=16,total=n*w+(n-1)*g,start=(798-total)/2;labels.forEach((l,i)=>{const x=start+i*(w+g);box(p,x,40,w,239,C.white,C.line,16);panelIcon(p,x+w/2,102,icons[i]||'step');lines(p,x+w/2,165,l,Math.floor((w-20)/11.5),22,C.ink,'middle',27);if(i<n-1&&v.focus==='flow')arrow(p,x+w+2,145,x+w+g-3,145,C.green);});}
function sensor(p,v){[90,300,510].forEach((x,i)=>pot(p,x,100,142,145,{probe:i===0}));box(p,65,24,285,47,C.white,C.orange,10);text(p,207,55,v.labels[0]||'One local sensing region',22,C.orange,'middle');line(p,198,71,191,140,C.orange,2);text(p,440,286,v.labels[1]||'Other pots still need checking',23,C.ink,'middle');if(v.labels[2])lines(p,450,45,v.labels[2],25,22);}
function fraction(p,v){const [a,b]=v.values||[6,10],n=Number(a),d=Number(b),valid=Number.isFinite(n)&&Number.isFinite(d)&&d>0&&n>=0&&n<=d,ratio=valid?n/d:0;
 box(p,40,48,350,143,'#e5e4df',C.ink,0);if(valid)add(p,'rect',{x:41,y:49,width:348*ratio,height:141,fill:C.water});if(Number.isInteger(d)&&d<=20){for(let i=1;i<d;i++)line(p,40+350*i/d,48,40+350*i/d,191,C.muted,1.5);}line(p,40+350*ratio,48,40+350*ratio,191,C.blue,3);text(p,215,228,valid?`${a} ÷ ${b} × 100 = ${Number((ratio*100).toFixed(3))}%`:'Check the sample volumes',26,C.ink,'middle',650);
 const labels=v.labels.length?v.labels:['Water volume','Total sample volume'];labelStack(p,labels.slice(0,3),430,40,330);
}
function capacity(p,v){const labels=v.labels.length?v.labels:['Saturated','After drainage','Configured reference'];if(['saturated','drained'].includes(v.focus)){pot(p,90,50,210,195,{wet:v.focus==='saturated',air:v.focus!=='saturated'});if(v.focus==='drained'){arrow(p,195,250,195,272);box(p,70,278,250,18,C.water,C.blue,4);}labelStack(p,labels.slice(0,3),390,43,365);}else if(v.focus==='comparison'||labels.length===2){pot(p,100,73,170,170,{wet:true,air:false});pot(p,480,73,170,170);lines(p,185,276,labels[0],24,22,C.ink,'middle');lines(p,565,276,labels[1],24,22,C.ink,'middle');arrow(p,298,150,442,150,C.blue);}else panels(p,v,['water','water','time']);}
// A3 only: a sponge is an analogy for pore spaces, never a literal pot test.
function spongeShape(p,x,y,w,h,wet=false){
 box(p,x,y,w,h,'#efd081','#9d7527',22);
 const holes=[[.16,.25],[.4,.18],[.68,.27],[.85,.2],[.26,.66],[.55,.65],[.82,.7]];
 holes.forEach(([a,b],i)=>add(p,'ellipse',{cx:x+a*w,cy:y+b*h,rx:w*.064,ry:h*.12,fill:wet||i%2===0?C.water:C.white,stroke:wet||i%2===0?C.blue:C.muted,'stroke-width':2}));
 if(wet)[.25,.53,.79].forEach(a=>add(p,'path',{d:`M ${x+a*w} ${y+h+8} q -10 15 0 22 q 10 -7 0 -22`,fill:C.water,stroke:C.blue,'stroke-width':1.5}));
}
function sponge(p,v){
 const labels=v.labels||[],focus=v.focus||'comparison';
 if(focus==='recall'){
  panelIcon(p,399,58,'question');
  lines(p,399,137,labels[0]||'Reference: 60% → 70%',43,28,C.ink,'middle',34);
  lines(p,399,211,labels[1]||'What happens to the water?',43,27,C.ink,'middle',33);
 }else if(focus==='comparison'){
  spongeShape(p,58,48,265,131,true);spongeShape(p,470,48,265,131,false);
  arrow(p,345,112,447,112,C.blue);
  lines(p,190,245,labels[0]||'Soaked and dripping',27,23,C.ink,'middle',29);
  lines(p,602,245,labels[1]||'Wet after drainage',27,23,C.ink,'middle',29);
 }else if(focus==='reference'){
  spongeShape(p,60,66,260,130,false);
  text(p,190,244,'Same physical sponge',22,C.ink,'middle');
  box(p,449,31,290,154,'#fff1a9','#c5a343',3);
  text(p,594,68,'REFERENCE NOTE',21,C.muted,'middle',700);
  text(p,594,119,'60% → 70%',35,C.ink,'middle',700);
  arrow(p,338,132,425,132,C.muted);
  labels.slice(0,2).forEach((l,i)=>lines(p,594,221+i*35,l,30,22,C.ink,'middle',27));
 }else if(focus==='volume'){
  pot(p,73,36,213,167,{wet:false,air:true});
  text(p,180,247,'Total sample: 1000 mL',22,C.ink,'middle');
  text(p,552,77,'600 mL water',28,C.blue,'middle',700);
  text(p,552,128,'600 ÷ 1000 × 100',28,C.ink,'middle');
  text(p,552,177,'= 60% VWC',33,C.blue,'middle',700);
  text(p,552,234,'Example, not a target',22,C.muted,'middle');
 }else if(focus==='transfer'){
  spongeShape(p,57,68,240,126,false);pot(p,478,50,178,162,{wet:false,air:true});
  arrow(p,326,127,443,127,C.green);
  labels.slice(0,2).forEach((l,i)=>lines(p,399,244+i*31,l,58,22,C.ink,'middle',26));
 }else{
  spongeShape(p,57,52,270,140,focus==='wet');
  line(p,48,245,337,245,C.muted,4);
  text(p,193,284,focus==='wet'?'Dripping over the sink':'Wet after excess drips',22,C.ink,'middle');
  labels.slice(0,2).forEach((l,i)=>{box(p,397,53+i*100,361,81,C.white,C.line,12);lines(p,415,86+i*100,l,28,23,C.ink,'start',28);});
 }
}
// Fixed synthetic observations: reference/threshold edits never modify these values.
const VWC=[46,45,44,43,54,51,57,54,60,56,53,50,47,44,42,40,39,38,37,36,35,34,33,32,31];
const EC=[2.8,2.9,3,3.05,2.9,3,2.85,2.95,2.8,2.9,3.05,3.1,3,3.2,3.25,3.3,3.2,3.3,3.35,3.4,3.3,3.45,3.4,3.5,3.4];
function graph(p,v){const focus=v.focus||'all',x=75,y=43,w=650,h=179,px=i=>x+i*w/24,vy=n=>y+h-(n-20)/40*h,ey=n=>y+h-(n-2)/2*h;
 box(p,x,y,w,h,C.white,C.line,0);add(p,'rect',{x:px(14),y,width:w*10/24,height:h,fill:'#edf0f7'});
 [20,40,60].forEach(n=>{line(p,x,vy(n),x+w,vy(n),C.line,1);text(p,x-12,vy(n)+7,`${n}`,20,focus==='vwc'?C.blue:C.muted,'end');});
 [2,3,4].forEach(n=>text(p,x+w+12,ey(n)+7,`${n}`,20,focus==='ec'?C.orange:C.muted));
 text(p,74,25,'VWC %',20,C.blue);text(p,650,25,'EC mS/cm',20,C.orange);[0,6,12,18,24].forEach((n,i)=>text(p,px(n),250,['06:00','12:00','18:00','00:00','06:00'][i],20,focus==='time'?C.ink:C.muted,'middle'));
 if(focus==='recall')text(p,260,25,'Example reading age: 2 min',20,C.muted);
 if(['events','reference','night','draft','recall'].includes(focus))[4,6,8].forEach(i=>{line(p,px(i),y,px(i),y+h,'#83ad98',2,'5 5');add(p,'path',{d:`M ${px(i)-6} ${y-8} l 12 0 l -6 8 Z`,fill:C.green});});
 const path=(arr,scale)=>arr.map((n,i)=>`${i?'L':'M'} ${px(i)} ${scale(n)}`).join(' ');
 add(p,'path',{d:path(VWC,vy),fill:'none',stroke:C.blue,'stroke-width':focus==='vwc'?5:3,opacity:focus==='time'?0.5:1});
 if(focus==='vwc'){add(p,'circle',{cx:px(8),cy:vy(60),r:7,fill:C.white,stroke:C.blue,'stroke-width':4});box(p,px(8)+18,vy(60)+10,134,41,C.white,C.blue,8);text(p,px(8)+85,vy(60)+38,'60% at 14:00',20,C.blue,'middle',650);}
 if(focus!=='vwc')add(p,'path',{d:path(EC,ey),fill:'none',stroke:C.orange,'stroke-width':focus==='ec'?5:3,opacity:focus==='time'?0.5:1});
 if(['reference','night','draft','recall'].includes(focus)){add(p,'path',{d:`M ${x} ${vy(45)} L ${px(8)} ${vy(52)} L ${px(14)} ${vy(44)} L ${px(24)} ${vy(40)}`,fill:'none',stroke:C.green,'stroke-width':3,'stroke-dasharray':'8 5'});add(p,'path',{d:`M ${px(8)} ${ey(3)} L ${px(14)} ${ey(3.1)} L ${px(24)} ${ey(2.9)}`,fill:'none',stroke:'#995bb0','stroke-width':3,'stroke-dasharray':'8 5'});}
 if(focus==='draft'){const before=v.values?.[0]??35,after=v.values?.[1]??39;line(p,x,vy(before),x+w,vy(before),C.muted,2,'5 5');line(p,x,vy(after),x+w,vy(after),'#bc4054',3,'10 4');text(p,x+10,vy(after)-9,`Draft ${after}%`,20,'#a52740');text(p,x+475,vy(before)+22,`Saved ${before}%`,20,C.muted);}
 const labels=v.labels.length?v.labels:['Blue: synthetic VWC','Orange: synthetic EC'];labels.slice(0,2).forEach((l,i)=>lines(p,45+i*385,273,l,34,20,C.ink,'start',25));
}
function demo(p,v){box(p,70,34,350,223,C.white,C.ink,13);box(p,90,55,310,160,C.pale,C.line,4);text(p,245,107,'DEMO',30,C.green,'middle',750);text(p,245,153,'Practice controls',23,C.ink,'middle');line(p,185,275,307,275,C.ink,5);line(p,245,258,245,275,C.ink,6);labelStack(p,v.labels.length?v.labels:['No real pump operation','Start with one zone'],458,52,300);}
function waterPath(p,v){v.labels.slice(0,3).forEach((l,i)=>{const y=41+i*89;line(p,43,y+27,102,y+27,C.blue,8);add(p,'circle',{cx:43,cy:y+27,r:11,fill:C.water,stroke:C.blue,'stroke-width':3});arrow(p,80,y+27,110,y+27,C.blue);box(p,120,y,635,66,C.white,C.blue,12);lines(p,142,y+28,l,52,22,C.ink,'start',27);});}
function protection(p,v){const x=110,y=129,r=66;add(p,'polygon',{points:Array.from({length:8},(_,i)=>{const a=Math.PI/8+i*Math.PI/4;return `${x+r*Math.cos(a)},${y+r*Math.sin(a)}`;}).join(' '),fill:'#fff0ee',stroke:'#b34336','stroke-width':4});text(p,x,y+9,'STOP',25,'#a53930','middle',750);labelStack(p,v.labels.slice(0,3),240,40,505);}
/** Render one narration paragraph as a fixed-size, self-contained video card. */
export function renderPilotCard(card){
 const el=document.createElement('article');el.className='pilot-card';el.dataset.card=card.id||'';Object.assign(el.style,{width:'854px',height:'480px',boxSizing:'border-box',position:'relative',overflow:'hidden',background:'#f7faf6',color:C.ink,fontFamily:'Arial, Helvetica, sans-serif',margin:'0',padding:'0'});
 // AI concept illustrations use a plain local image; exact arithmetic stays SVG.
 const asset=card.visual?.asset;
 if(typeof asset==='string' && /^assets\/(?:diagrams|screens)\/[a-zA-Z0-9_./-]+\.(?:png|jpe?g|webp)$/.test(asset) && !asset.includes('..')){
  el.dataset.visualMode='asset';
  const img=document.createElement('img');img.src=asset;img.alt=card.visual.alt||card.title||'Teaching illustration';img.decoding='sync';
  Object.assign(img.style,{display:'block',width:'854px',height:'480px',objectFit:'contain',background:'#f7faf6'});el.append(img);return el;
 }
 const stripe=document.createElement('div');Object.assign(stripe.style,{height:'7px',background:C.green});el.append(stripe);
 const meta=document.createElement('div');meta.textContent=`CROP STEERING · ${card.lesson||''} · ${card.id||''}`;Object.assign(meta.style,{position:'absolute',left:'28px',top:'20px',fontSize:'16px',fontWeight:'700',letterSpacing:'1px',color:C.muted});el.append(meta);
 const heading=document.createElement('h1');heading.textContent=card.title||'';Object.assign(heading.style,{position:'absolute',left:'28px',right:'28px',top:'45px',margin:'0',fontSize:'29px',lineHeight:'35px',fontWeight:'700'});el.append(heading);
 const svg=s('svg',{viewBox:'0 0 798 307',width:798,height:307,role:'img','aria-label':card.title||'',style:'position:absolute;left:28px;top:94px;font-family:Arial,Helvetica,sans-serif;overflow:visible'});el.append(svg);
 const v={type:'process',labels:[],...card.visual};
 switch(v.type){case 'sponge':sponge(svg,v);break;case 'root-zone':rootZone(svg,v);break;case 'drainage':drainage(svg,v);break;case 'losses':losses(svg,v);break;case 'sensor':sensor(svg,v);break;case 'fraction':fraction(svg,v);break;case 'capacity':capacity(svg,v);break;case 'graph':graph(svg,v);break;case 'demo':demo(svg,v);break;
 case 'water-path':waterPath(svg,v);break;case 'protection':protection(svg,v);break;case 'commissioning':panels(svg,v,['water','time','check']);break;case 'equipment':panels(svg,v,['host','sensor','water','time','check']);break;
 case 'question':panels(svg,v,v.labels.map(l=>/^water$/i.test(l)?'water':/^oxygen$/i.test(l)?'plant':'question'));break;case 'check':panels(svg,v,['plant','check','sensor']);break;
 case 'steering':panels(svg,v,['plant','plant','plant']);break;
 case 'controls':panels(svg,v,['time','water',/light|heat|humidity/i.test(v.labels[2]||'')?'sun':'time']);break;case 'environment':panels(svg,v,['sun','temperature','water']);break;case 'evidence':panels(svg,v,['sensor','check','plant']);break;case 'host':panels(svg,v,['host','host','check']);break;
 default:panels(svg,v);}
 return el;
}
