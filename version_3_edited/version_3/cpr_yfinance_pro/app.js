const $=id=>document.getElementById(id);let latest=null,lastPhase='idle',remoteVersion=null;
const APP_VERSION='2.1.0';
const fmt=n=>Number(n||0).toLocaleString('en-US');
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function isNewerVersion(candidate,current){
 const parts=value=>String(value).split('.').map(Number);
 const next=parts(candidate),installed=parts(current);
 if(!next.length||next.length!==installed.length||next.some(part=>!Number.isInteger(part)||part<0)||installed.some(part=>!Number.isInteger(part)||part<0))return false;
 for(let i=0;i<next.length;i++){if(next[i]!==installed[i])return next[i]>installed[i]}
 return false;
}
function sectorOptions(sectors){for(const id of ['sector','viewsector']){const el=$(id);for(const s of sectors){if(!Array.from(el.options).some(o=>o.value===s)){const op=document.createElement('option');op.value=s;op.textContent=s;el.appendChild(op)}}}}
function numeric(id){const v=$(id).value;return v===''?null:Number(v)}
function filterRanges(){
 const advCustom=$('advFilter').value==='custom',priceCustom=$('priceFilter').value==='custom';
 $('customFilters').hidden=!(advCustom||priceCustom);
 $('advCustomLabel').hidden=!advCustom;$('priceCustomLabel').hidden=!priceCustom;
}
function matchesPrice(price){
 const v=$('priceFilter').value;if(v==='any'||v==='custom')return true;
 if(v.endsWith('+'))return price>=Number(v.slice(0,-1));
 const [lo,hi]=v.split('-').map(Number);return price>=lo&&price<=hi;
}
function render(){
 if(!latest)return;
 const q=$('search').value.toLowerCase().trim(),sector=$('viewsector').value,sort=$('sort').value;
 const advMode=$('advFilter').value,advMin=advMode==='custom'?(numeric('advMin')??0):advMode==='any'?0:Number(advMode),advMax=advMode==='custom'?numeric('advMax'):null;
 const priceMode=$('priceFilter').value,priceMin=priceMode==='custom'?(numeric('priceMin')??0):null,priceMax=priceMode==='custom'?numeric('priceMax'):null;
 let rows=latest.rows.filter(r=>(sector==='All'||r.sector===sector)&&[r.symbol,r.sector,r.exchange].some(x=>String(x).toLowerCase().includes(q))&&r.adv>=advMin&&(advMax===null||r.adv<=advMax)&&matchesPrice(r.close)&&(priceMode!=='custom'||(r.close>=priceMin&&(priceMax===null||r.close<=priceMax))));
 rows.sort((a,b)=>sort==='symbol'?a.symbol.localeCompare(b.symbol):sort==='adv'?b.adv-a.adv:b.strength-a.strength);
 $('count').textContent=fmt(rows.length)+' securities';$('rows').innerHTML=rows.length?rows.map(r=>`<tr><td><strong>${esc(r.symbol)}</strong><div class="symboltag">${esc(r.exchange)}</div></td><td><span class="sectorchip">${esc(r.sector)}</span></td><td>$${fmt(r.close)}</td><td>${fmt(r.adv)}</td><td>$${r.weekly.low.toFixed(2)} – $${r.weekly.high.toFixed(2)}</td><td>$${r.monthly.low.toFixed(2)} – $${r.monthly.high.toFixed(2)}</td><td>$${r.overlap.low.toFixed(2)} – $${r.overlap.high.toFixed(2)}</td><td><span class="strength">${r.strength.toFixed(1)}/100</span><div class="strengthbar"><span style="width:${Math.max(0,Math.min(100,r.strength))}%"></span></div></td></tr>`).join(''):'<tr><td colspan="8" class="empty"><div class="emptyicon">◎</div><strong>No matching stocks</strong><p>These filters only show stocks that already have weekly/monthly CPR confluence. Broaden the ADV or price range.</p></td></tr>';
}
function show(data){
 const s=data.scan;sectorOptions(data.sectors||[]);$('scan').disabled=s.phase==='scanning';
 $('status').textContent=({idle:'Ready to scan',scanning:'Scan in progress',complete:'Scan complete',error:'Scan failed'})[s.phase]||s.phase;
 let p=s.progress||{},pct=p.total?Math.round(p.done/p.total*100):0;$('percent').textContent=pct+'%';$('bar').style.width=pct+'%';
 $('stage').textContent=s.phase==='error'?s.error:s.phase==='scanning'?`${p.stage||'Preparing scan'} · ${fmt(p.done)}/${fmt(p.total)} · ${fmt(p.matches)} matches`:s.phase==='complete'?'All batches processed. Results are ready.':'Select a sector and run the screener.';
 if(s.result){latest=s.result;const st=latest.stats;for(const [id,k] of [['universe','universe'],['analyzed','downloaded'],['matches','matches'],['failed','failed']])$(id).textContent=fmt(st[k]);$('periods').textContent=`Week ${latest.periods.week} · Month ${latest.periods.month}`;$('updated').textContent='Last scan: '+new Date(latest.generatedAt).toLocaleString();$('export').disabled=false;render()}
 if(s.phase!==lastPhase){lastPhase=s.phase;if(s.phase==='error')console.error('CPR scan failed:',s.error)}
}
async function poll(){try{const r=await fetch('/api/status',{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);show(await r.json())}catch(e){$('status').textContent='Server disconnected';$('stage').textContent=e.message}}
async function pollVersion(){
 try{const r=await fetch('/api/version',{cache:'no-store'});if(!r.ok)return;const v=await r.json();if(!v.version||!v.message)return;remoteVersion=v;
 const seen=localStorage.getItem('cpr_seen_update')||'';
 const isNew=isNewerVersion(v.version,APP_VERSION)&&seen!==String(v.version);
 $('updateDot').hidden=!isNew;$('updateBanner').hidden=!isNew;
 if(isNew){$('updateTitle').textContent=`Version ${v.version} available${v.publishedAt?' · '+new Date(v.publishedAt).toLocaleString():''}`;$('updateMessage').textContent=v.message;}
 }catch(e){/* Update notifications are optional; keep the scanner usable offline. */}
}
$('scan').addEventListener('click',async()=>{const limit=$('limit').value;try{const r=await fetch('/api/scan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sector:$('sector').value,limit:limit?Number(limit):null})});const j=await r.json();if(!r.ok)throw Error(j.error||'Unable to start scan');$('viewsector').value=$('sector').value;await poll()}catch(e){$('status').textContent='Could not start';$('stage').textContent=e.message}});
for(const id of ['search','viewsector','sort','advFilter','priceFilter','advMin','advMax','priceMin','priceMax'])$(id).addEventListener(id==='search'||id.endsWith('Min')||id.endsWith('Max')?'input':'change',()=>{if(id==='advFilter'||id==='priceFilter')filterRanges();render()});
$('publishUpdate').addEventListener('click',async()=>{
 const message=prompt('Describe what changed. This will appear as a red update notification for your team:');if(!message||!message.trim())return;
 const btn=$('publishUpdate');btn.disabled=true;
 try{const r=await fetch('/api/version/publish',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:message.trim(),clientVersion:APP_VERSION})});const j=await r.json();if(!r.ok)throw Error(j.error||'Could not publish update');alert(`Update notification published: ${j.version}`);await pollVersion();}
 catch(e){alert('Update was not published: '+e.message+'. Check CPR_UPDATE_URL and CPR_UPDATE_TOKEN on your local server.');}
 finally{btn.disabled=false;}
});
$('dismissUpdate').addEventListener('click',()=>{if(remoteVersion?.version)localStorage.setItem('cpr_seen_update',String(remoteVersion.version));$('updateBanner').hidden=true;$('updateDot').hidden=true});
$('export').addEventListener('click',()=>{if(!latest)return;const cols=['symbol','exchange','sector','close','adv','weekly_low','weekly_high','weekly_pivot','monthly_low','monthly_high','monthly_pivot','overlap_low','overlap_high','strength','weeks_observed','weeks_inside','overlapping_pairs','compression_points'];const lines=[cols.join(',')];for(const r of latest.rows){lines.push([r.symbol,r.exchange,r.sector,r.close,r.adv,r.weekly.low,r.weekly.high,r.weekly.pivot,r.monthly.low,r.monthly.high,r.monthly.pivot,r.overlap.low,r.overlap.high,r.strength,r.scoreBreakdown?.weeksObserved,r.scoreBreakdown?.weeksInside,r.scoreBreakdown?.overlappingPairs,r.scoreBreakdown?.compression].map(x=>'"'+String(x).replace(/"/g,'""')+'"').join(','))}const blob=new Blob([lines.join('\n')],{type:'text/csv'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='cpr_atlas_results.csv';a.click();URL.revokeObjectURL(url)});
function clock(){$('clock').textContent=new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',hour:'2-digit',minute:'2-digit',hour12:true}).format(new Date())+' ET'}
clock();setInterval(clock,30000);filterRanges();poll();pollVersion();setInterval(poll,2000);setInterval(pollVersion,10000);
