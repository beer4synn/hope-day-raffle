'use strict';
const $=id=>document.getElementById(id),page=document.body.dataset.page;
const quotas={1:1,2:5,3:3,4:3};
let csrf='',state=null,busy=false,lastCount=null,lastDraw='',revealTimer=null,receiptReady=false;
function message(text){$('message').textContent=text||'';}
async function api(path,data){
 // Refresh against the current HttpOnly session cookie before each mutation.
 // Another tab may have signed in, or initial session loading may have failed.
 if(data!==undefined && path.startsWith('/api/admin/')){
  csrf=(await api('/api/admin/session')).csrf;
 }
 const response=await fetch(path,{method:data===undefined?'GET':'POST',headers:data===undefined?{}:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:data===undefined?undefined:JSON.stringify(data),cache:'no-store'});
 let result; try{result=await response.json();}catch{throw new Error('서버 연결을 확인해 주세요.');}
 if(!response.ok){const e=new Error(result.error||'요청을 처리하지 못했습니다.');e.status=response.status;throw e;}
 return result;
}
function label(entry){return entry.nickname+' · '+entry.ending;}
function list(id,entries,numbers=false){$(id).replaceChildren(...entries.map(e=>{const li=document.createElement('li');li.textContent=label(e);if(numbers){const n=document.createElement('small');n.textContent='응모번호 '+String(e.number).padStart(3,'0');li.append(n);}return li;}));}
function receipt(r){receiptReady=true;$('receiptNumber').textContent=String(r.number).padStart(3,'0');$('receiptLabel').textContent=label(r);$('joinCard').hidden=true;$('receiptCard').hidden=false;}
async function joinStatus(){if(receiptReady)return;try{const s=await api('/api/status');$('joinStatus').textContent=s.open?'접수 중':'접수 대기 / 마감';$('joinButton').disabled=!s.open||busy;}catch{ $('joinStatus').textContent='연결 확인 필요';$('joinButton').disabled=true;}}
if(page==='join'){
 $('joinForm').onsubmit=async e=>{e.preventDefault();if(busy)return;busy=true;$('joinButton').disabled=true;message('');try{const r=await api('/api/register',{nickname:$('nickname').value,phone:$('phone').value,consent:$('consent').checked});$('phone').value='';try{localStorage.setItem('hope-receipt',r.receipt);}catch{}receipt(r);}catch(e){message(e.message);}finally{busy=false;await joinStatus();}};
 (async()=>{try{const token=localStorage.getItem('hope-receipt');if(token)receipt(await api('/api/receipt',{receipt:token}));}catch(e){if(e.status!==404)message('이전 접수증을 불러오지 못했습니다. 연결 후 새로고침해 주세요.');}await joinStatus();setInterval(joinStatus,5000);})();
}
function renderAdmin(){
 $('registrationState').textContent=state.is_open?'접수 중':'접수 마감';$('total').textContent=state.count+'명 접수';
 $('openRegistration').disabled=busy||!!state.is_open||Object.values(state.results).some(a=>a.length);
 $('closeRegistration').disabled=busy||!state.is_open;
 list('adminRecent',state.recent,true);
 const rank=$('rank').value,result=state.results[rank];
 $('pick').disabled=busy||!!state.is_open||state.view!=='draw'||state.rank!==Number(rank)||result.length>0;
 $('pick').textContent=result.length?'당첨 결과 저장됨':'당첨자 뽑기';
 $('savePrize').disabled=busy||result.length>0;
 $('drawInfo').textContent=rank+'등 · '+quotas[rank]+'명 · '+state.prizes[rank]+(result.length?' · 추첨 완료':' · 추첨 전');list('adminWinners',result,true);
}
async function action(path,data){if(busy)return;busy=true;renderAdmin();message('');try{state=await api(path,data);renderAdmin();}catch(e){message(e.message);}finally{busy=false;renderAdmin();}}
async function pollAdmin(){try{state=await api('/api/admin/state');$('loginCard').hidden=true;$('adminContent').hidden=false;$('liveStatus').textContent='서버 연결됨 · '+new Date().toLocaleTimeString('ko-KR');renderAdmin();}catch(e){if(e.status===401){$('loginCard').hidden=false;$('adminContent').hidden=true;csrf='';}else{$('liveStatus').textContent='연결 끊김 · 조작 전 연결을 확인해 주세요.';if($('pick'))$('pick').disabled=true;}}}
if(page==='admin'){
 $('loginForm').onsubmit=async e=>{e.preventDefault();if(busy)return;busy=true;try{csrf=(await api('/api/login',{password:$('password').value})).csrf;$('password').value='';message('');await pollAdmin();$('prize').value=state.prizes[$('rank').value];}catch(e){message(e.message);}finally{busy=false;if(state)renderAdmin();}};
 $('openRegistration').onclick=()=>action('/api/admin/registration',{open:true});
 $('closeRegistration').onclick=()=>action('/api/admin/registration',{open:false});
 $('openDraw').onclick=()=>action('/api/admin/screen',{view:'draw',rank:Number($('rank').value)});
 $('back').onclick=()=>action('/api/admin/screen',{view:'waiting',rank:Number($('rank').value)});
 $('pick').onclick=()=>action('/api/admin/draw',{rank:Number($('rank').value)});
 $('savePrize').onclick=()=>action('/api/admin/prize',{rank:Number($('rank').value),name:$('prize').value});
 $('rank').onchange=()=>{if(state){$('prize').value=state.prizes[$('rank').value];renderAdmin();}};
 $('logout').onclick=async()=>{try{await api('/api/admin/logout',{});state=null;csrf='';$('loginCard').hidden=false;$('adminContent').hidden=true;}catch(e){message(e.message);}};
 (async()=>{try{csrf=(await api('/api/admin/session')).csrf;await pollAdmin();if(state)$('prize').value=state.prizes[$('rank').value];}catch{}setInterval(pollAdmin,1500);})();
}
function display(s){
 $('displayIntro').textContent=s.is_open?'휴대폰 카메라로 QR을 찍고 경품 추첨에 참여하세요.':'접수가 마감되었습니다. 행운의 주인공을 기다려 주세요!';
 $('qrCaption').textContent=s.is_open?'휴대폰으로 응모하기':'접수 대기 / 마감';$('joinAddress').textContent=location.origin+'/';
 $('count').textContent=s.count;
 if(lastCount!==s.count){list('recent',s.recent);$('friends').textContent=['🎁','🐣','🐰','🐻','🦊'].slice(0,1+Math.min(4,Math.ceil(s.count/15))).join(' ');$('friends').classList.remove('hop');if(lastCount!==null)requestAnimationFrame(()=>requestAnimationFrame(()=>$('friends').classList.add('hop')));lastCount=s.count;}
 $('waiting').hidden=s.view==='draw';$('draw').hidden=s.view!=='draw';
 const result=s.results[String(s.rank)],key=String(s.rank)+':'+result.map(e=>e.number).join(',');
 $('drawTitle').textContent=s.rank+'등 '+(result.length?'당첨자':'추첨');$('displayPrize').textContent=s.prizes[String(s.rank)];
 if(key!==lastDraw||s.view!=='draw'){
 clearTimeout(revealTimer);$('draw').classList.remove('pulse');
 const animate=s.view==='draw'&&result.length>0&&lastDraw===String(s.rank)+':';
 list('winners',animate?[]:result,true);$('drawStatus').textContent=result.length?'축하합니다!':quotas[s.rank]+'명을 추첨합니다.';
 if(animate){$('drawStatus').textContent='두근두근… 추첨 중!';$('draw').classList.add('pulse');revealTimer=setTimeout(()=>{$('draw').classList.remove('pulse');list('winners',result,true);$('drawStatus').textContent='축하합니다!';},900);}
 lastDraw=key;
 }
}
if(page==='display'){
 $('full').onclick=()=>document.fullscreenElement?document.exitFullscreen():document.documentElement.requestFullscreen();
 async function poll(){try{const s=await api('/api/admin/state');$('connection').hidden=true;message('');display(s);}catch(e){$('connection').hidden=false;if(e.status===401){message('운영자 로그인이 필요합니다. 운영자 화면에서 로그인한 뒤 새로고침해 주세요.');$('waiting').hidden=true;$('draw').hidden=true;}}}
 poll();setInterval(poll,1000);
}
