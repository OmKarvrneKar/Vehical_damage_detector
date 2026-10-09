const $ = id => document.getElementById(id);
const inr = n => '₹' + Number(n).toLocaleString('en-IN');
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
let file = null, stream = null;

function showErr(m) { $('err').textContent = m; $('err').hidden = !m; }
function pick(f) {
  if (!f) return;
  if (!/\.(jpe?g|png)$/i.test(f.name)) return showErr('Only JPG, JPEG or PNG images are supported.');
  file = f; showErr('');
  $('preview').src = URL.createObjectURL(f); $('preview').hidden = false;
  $('dropText').textContent = f.name; $('name').value = f.name; $('folder').value = '(selected from your computer)';
}
$('browse').onclick = () => $('file').click();
$('file').onchange = e => pick(e.target.files[0]);
['dragover', 'dragenter'].forEach(ev => $('drop').addEventListener(ev, e => { e.preventDefault(); $('drop').classList.add('over'); }));
['dragleave', 'drop'].forEach(ev => $('drop').addEventListener(ev, e => { e.preventDefault(); $('drop').classList.remove('over'); }));
$('drop').addEventListener('drop', e => pick(e.dataTransfer.files[0]));
$('drop').addEventListener('keydown', e => { if (e.key === 'Enter') $('file').click(); });

// camera snapshot
function stopCam() { if (stream) stream.getTracks().forEach(t => t.stop()); stream = null; $('cam').hidden = true; }
$('camBtn').onclick = async () => {
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } });
    $('video').srcObject = stream; $('cam').hidden = false;
  } catch { showErr('Could not open the camera. Allow camera access in your browser, or upload a photo instead.'); }
};
$('camOff').onclick = stopCam;
$('snap').onclick = () => {
  const v = $('video'), c = document.createElement('canvas');
  c.width = v.videoWidth; c.height = v.videoHeight; c.getContext('2d').drawImage(v, 0, 0);
  c.toBlob(b => { pick(new File([b], `camera_${Date.now()}.jpg`, { type: 'image/jpeg' })); stopCam(); }, 'image/jpeg', 0.92);
};

$('go').onclick = async () => {
  const fd = new FormData();
  if (file && $('name').value === file.name) fd.append('image', file);
  else { fd.append('folder', $('folder').value); fd.append('name', $('name').value); }
  $('go').disabled = true; $('go').textContent = 'Analysing…'; showErr('');
  try {
    const res = await fetch('/api/detect-damage', { method: 'POST', body: fd });
    if (res.status === 401) return (location.href = '/');
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Analysis failed.');
    render(data);
  } catch (e) { showErr(e.message); }
  $('go').textContent = 'Analyse image'; $('go').disabled = false; loadHistory();
};

$('again').onclick = () => {
  file = null; $('file').value = ''; $('preview').hidden = true; $('dropText').textContent = 'Drop a JPG or PNG here';
  $('name').value = ''; $('folder').value = ''; $('report').hidden = true;
  $('inputPanel').scrollIntoView({ behavior: 'smooth' });
};

function render(r) {
  $('report').hidden = false;
  $('rTitle').textContent = r.damaged ? 'Damage detected' : 'No damage detected';
  $('rMeta').textContent = `Report ${r.id} · ${r.date}`;
  $('rSev').textContent = r.damaged ? r.severity : 'Clear';
  $('rSev').className = 'sev ' + (r.damaged ? r.severity.toLowerCase() : 'none');
  $('warn').textContent = r.warning; $('warn').hidden = !r.warning;
  $('steps').innerHTML = r.steps.map(s => `<figure><img src="/uploads/${s.file}" alt="${esc(s.label)}"><figcaption>${esc(s.label)}</figcaption></figure>`).join('');
  $('rImg').src = '/uploads/' + r.annotated;
  const facts = [['Vehicle type', r.vehicle.label], ['Damage detected', r.damaged ? 'Yes' : 'No'],
    ['Damage type', r.damage_types.join(', ') || '-'], ['Severity', r.damaged ? r.severity : '-'],
    ['Confidence', r.confidence + '%'], ['Engine', r.engine]];
  $('facts').innerHTML = facts.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join('');
  $('rCost').textContent = r.damaged ? `${inr(r.cost.min)} – ${inr(r.cost.max)}` : '₹0';
  $('rSplit').textContent = r.damaged ? `Labour ${inr(r.cost.labour)} · Parts ${inr(r.cost.parts)}` : '';
  $('dmg').innerHTML = r.damages.length ? '<table><thead><tr><th>Type</th><th>Confidence</th><th>Size (px)</th></tr></thead><tbody>' +
    r.damages.map(d => `<tr><td>${esc(d.type)}</td><td>${(d.conf * 100).toFixed(1)}%</td><td>${d.w}×${d.h}</td></tr>`).join('') + '</tbody></table>'
    : '<p class="muted">Nothing to repair.</p>';
  $('parts').innerHTML = r.parts.length ? r.parts.map(p => `<div class="part"><div><b>${esc(p.name)}</b>
    <span class="muted">${esc(p.damage)} → ${p.action}</span></div>` + (p.prices.length ?
    `<table><tbody>${p.prices.map((x, i) => `<tr class="${i === p.prices.length - 1 ? 'best' : ''}"><td>${x.vendor}</td><td>${inr(x.price)}</td><td>${x.delivery}</td></tr>`).join('')}</tbody></table>` :
    '<p class="muted">Repairable without a new part.</p>') + '</div>').join('') : '<p class="muted">No parts needed.</p>';
  $('rec').textContent = r.recommendation;
  $('stages').innerHTML = r.stages.map(s => `<li>${s.stage} <span class="muted">${s.ms} ms</span></li>`).join('');
  $('report').scrollIntoView({ behavior: 'smooth' });
}

async function loadHistory() {
  const rows = await (await fetch('/api/history')).json();
  $('hist').innerHTML = rows.length ? rows.map(r => `<tr><td>${esc(r['Report ID'])}</td><td>${esc(r['Timestamp'])}</td><td>${esc(r['Image Name'])}</td>
    <td>${esc(r['Vehicle'])}</td><td>${esc(r['Damage Type'])}</td><td>${esc(r['Severity Level'])}</td>
    <td>${r['Confidence (%)'] == null ? '-' : r['Confidence (%)'] + '%'}</td><td>${esc(r['Estimated Repair Cost Range'])}</td><td>${esc(r['Status'])}</td></tr>`).join('')
    : '<tr><td colspan="9" class="muted">No reports yet. Analyse a photo above to create one.</td></tr>';
}
loadHistory();
