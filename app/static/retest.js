const rt={busy:false};const fb=document.querySelector('#feedback');
function lock(v){document.querySelectorAll('button').forEach(b=>b.disabled=v)}
async function post(url,payload){const options={method:'POST'};if(payload instanceof FormData){options.body=payload}else{options.headers={'Content-Type':'application/json'};options.body=JSON.stringify(payload)}const r=await fetch(url,options);const d=await r.json();if(!r.ok)throw Error(d.message||'请求失败，请重试');return d}
async function run(fn){if(rt.busy)return;rt.busy=true;fb.textContent='正在处理…';lock(true);try{await fn()}catch(e){fb.textContent=e.message}finally{rt.busy=false;lock(false)}}
function limit(){const v=document.querySelector('#limit').value;return v?{limit:Number(v)}:{}}
document.querySelector('#submit').addEventListener('click',()=>run(async()=>{await post('/api/retest',{csv:document.querySelector('#csv').value,...limit()});location.reload()}));
document.querySelector('#upload').addEventListener('click',()=>run(async()=>{const f=document.querySelector('#file').files[0];if(!f){fb.textContent='先选择CSV文件。';return}const form=new FormData();form.append('file',f);await post('/api/retest',form);location.reload()}));
document.querySelector('#samples').addEventListener('click',()=>run(async()=>{const[s1,s2]=JSON.parse(document.querySelector('#samples-data').textContent);await post('/api/retest',{csv:s1});await post('/api/retest',{csv:s2});location.href='/retest'}));
document.querySelectorAll('[data-resume]').forEach(b=>b.addEventListener('click',()=>run(async()=>{await post('/api/retest/resume',{job_id:b.dataset.resume,...limit()});location.reload()})));
const so=document.querySelector('#signoff');if(so)so.addEventListener('click',()=>run(async()=>{const d=await post('/api/retest/signoff',{batch:so.dataset.batch});location.href='/retest?batch='+encodeURIComponent(so.dataset.batch)+'&view=signed&signoff='+d.signoff_id}));
