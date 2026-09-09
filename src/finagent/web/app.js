const el = id => document.getElementById(id);
let currentId = null;
let pendingSubmission = null;
let pendingDecision = null;
function token(reviewer = false) { return el(reviewer ? 'review-token' : 'submit-token').value; }
function status(message, error = false) { el('status').textContent = message; el('status').className = `status${error ? ' error' : ''}`; }
async function api(path, options = {}, reviewer = false) {
  const response = await fetch(path, { ...options, headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token(reviewer)}`, ...options.headers }});
  const body = await response.json();
  if (!response.ok) throw new Error(body.error?.message || body.error || (body.detail ? JSON.stringify(body.detail) : 'Request failed.'));
  return body;
}
function render(record) {
  currentId = record.case_id;
  el('case-id').textContent = currentId;
  el('resume-id').value = currentId;
  el('result').hidden = false;
  el('classification').textContent = (record.assessment?.recommendation || record.status).replaceAll('_', ' ');
  el('model-summary').textContent = record.draft?.summary || record.assessment?.reason || record.error?.message || '';
  status(record.status === 'review_recorded' ? `Decision recorded by ${record.review.reviewer}: ${record.review.decision.replaceAll('_', ' ')}` : record.status.replaceAll('_', ' '), record.status === 'model_error');
  el('evidence').replaceChildren();
  for (const citation of record.draft?.citations || []) {
    const source = record.evidence.find(item => item.id === citation.chunk_id);
    const quote = document.createElement('blockquote'); quote.textContent = citation.quote;
    const label = document.createElement('p'); label.className = 'citation'; label.textContent = `${source.title} · ${citation.chunk_id} · ${source.version}`;
    const digest = document.createElement('p'); digest.className = 'citation'; digest.textContent = `SHA-256: ${source.sha256}`;
    el('evidence').append(quote, label, digest);
  }
  el('decision-panel').hidden = record.status !== 'awaiting_review';
  el('retry-button').hidden = record.status !== 'model_error';
  const approve = el('decision').querySelector('[value="approve_exception"]');
  approve.disabled = record.assessment?.recommendation === 'missing_receipt';
  if (approve.disabled) el('decision').value = 'request_information';
  el('audit').replaceChildren();
  for (const event of record.audit) { const row = document.createElement('li'); row.textContent = `${event.kind.replaceAll('_', ' ')} · ${new Date(event.created_at).toLocaleString()}`; el('audit').append(row); }
  el('record').textContent = JSON.stringify(record, null, 2);
}
el('expense-form').addEventListener('submit', async event => {
  event.preventDefault(); el('submit-button').disabled = true; status('Retrieving policy evidence and calling the local model…');
  const expense = {expense_id: el('expense-id').value, category: el('category').value, amount_cents: Math.round(Number(el('amount').value) * 100), currency: 'USD', receipt_present: el('receipt').checked, business_purpose: el('purpose').value};
  const body = JSON.stringify(expense);
  if (!pendingSubmission || pendingSubmission.body !== body) pendingSubmission = {id: crypto.randomUUID(), body};
  try { render(await api('/api/reviews', {method:'POST', headers:{'Idempotency-Key':pendingSubmission.id}, body})); pendingDecision = null; }
  catch (error) { status(error.message, true); }
  finally { el('submit-button').disabled = false; }
});
el('load-button').addEventListener('click', async () => { try { render(await api(`/api/reviews/${encodeURIComponent(el('resume-id').value.trim())}`)); pendingDecision = null; } catch(error) {status(error.message,true);} });
el('decision-form').addEventListener('submit', async event => {
  event.preventDefault(); const fields = {decision:el('decision').value,note:el('note').value};
  const key = JSON.stringify(fields); if (!pendingDecision || pendingDecision.key !== key) pendingDecision = {key,id:crypto.randomUUID()};
  try {render(await api(`/api/reviews/${currentId}/decision`,{method:'POST',body:JSON.stringify({...fields,decision_id:pendingDecision.id})},true));} catch(error) {status(error.message,true);}
});
el('retry-button').addEventListener('click', async () => {try {status('Retrying the local model…'); render(await api(`/api/reviews/${currentId}/retry`,{method:'POST'}));}catch(error){status(error.message,true);}});
